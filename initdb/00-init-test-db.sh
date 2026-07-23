#!/bin/sh
# Runs automatically on first container start, alongside schema.sql (which
# applies to the main $POSTGRES_DB database). This script creates a second,
# throwaway "cdo_test" database with the same schema, so the test suite
# (tests/test_server.py) can truncate/repopulate it freely without ever
# touching the real dev data in the main database.
set -e

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" -c "CREATE DATABASE cdo_test"
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname cdo_test -f /docker-entrypoint-initdb.d/schema.sql
