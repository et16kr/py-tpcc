# -*- coding: utf-8 -*-

import logging
import re

from .abstractdriver import AbstractDriver


class AltibaseDriver(AbstractDriver):
    DEFAULT_CONFIG = {
        "dsn": ("The Altibase ODBC DSN", "ALTIBASE_LOCAL"),
        "user": ("The username to connect to Altibase", "PYTPCC"),
        "password": ("The password to connect to Altibase", "PYTPCC"),
        "connection-timeout": ("The pyodbc connection timeout in seconds", "5"),
        "max-retries": ("The maximum transaction retry count", "20"),
        "retry-delay": ("The base transaction retry delay in seconds", "0.1"),
        "fast-executemany": ("Enable pyodbc cursor.fast_executemany during load", "False"),
    }

    DROP_TABLES = [
        "ORDER_LINE",
        "NEW_ORDER",
        "ORDERS",
        "HISTORY",
        "CUSTOMER",
        "STOCK",
        "DISTRICT",
        "ITEM",
        "WAREHOUSE",
    ]

    TRUE_VALUES = set(["1", "yes", "true", "on"])
    FALSE_VALUES = set(["0", "no", "false", "off"])

    def __init__(self, ddl):
        super(AltibaseDriver, self).__init__("altibase", ddl)
        self.conn = None
        self.cursor = None
        self.dsn = None
        self.user = None
        self.password = None
        self.connection_timeout = None
        self.max_retries = None
        self.retry_delay = None
        self.fast_executemany = None

    def makeDefaultConfig(self):
        return AltibaseDriver.DEFAULT_CONFIG

    def loadConfig(self, config):
        for key in AltibaseDriver.DEFAULT_CONFIG.keys():
            assert key in config, "Missing parameter '%s' in %s configuration" % (key, self.name)

        self.dsn = str(config["dsn"])
        self.user = str(config["user"])
        self.password = str(config["password"])
        self.connection_timeout = self._parse_int(config["connection-timeout"], "connection-timeout")
        self.max_retries = self._parse_int(config["max-retries"], "max-retries")
        self.retry_delay = self._parse_float(config["retry-delay"], "retry-delay")
        self.fast_executemany = self._parse_bool(config["fast-executemany"], "fast-executemany")

        self.conn = self._connect()
        self.cursor = self.conn.cursor()

        if self._parse_bool(config.get("reset", False), "reset"):
            try:
                self._reset_schema()
                self._execute_ddl_file()
                self.conn.commit()
            except Exception:
                self.conn.rollback()
                raise

    def _connect(self):
        try:
            import pyodbc
        except ImportError as ex:
            raise ImportError("AltibaseDriver requires pyodbc to connect. Install pyodbc or use --print-config without loading.") from ex

        connection_string = "DSN=%s;UID=%s;PWD=%s" % (self.dsn, self.user, self.password)
        logging.debug("Connecting to Altibase DSN '%s' as user '%s'", self.dsn, self.user)
        return pyodbc.connect(connection_string, timeout=self.connection_timeout)

    def _reset_schema(self):
        for table_name in AltibaseDriver.DROP_TABLES:
            try:
                logging.debug("Dropping Altibase table '%s'", table_name)
                self.cursor.execute("DROP TABLE %s" % table_name)
            except Exception as ex:
                if self._is_table_not_found_error(ex):
                    logging.debug("Ignoring missing Altibase table '%s': %s", table_name, ex)
                    continue
                raise

    def _execute_ddl_file(self):
        logging.debug("Loading Altibase DDL file '%s'", self.ddl)
        with open(self.ddl, "r") as ddl_file:
            for statement in self._split_ddl_statements(ddl_file.read()):
                logging.debug("Executing Altibase DDL statement: %s", statement)
                self.cursor.execute(statement)

    def _split_ddl_statements(self, ddl):
        lines = []
        for line in ddl.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("--"):
                continue
            lines.append(line)

        return [statement.strip() for statement in "\n".join(lines).split(";") if statement.strip()]

    def _is_table_not_found_error(self, ex):
        for arg in getattr(ex, "args", []):
            if arg == 200753:
                return True
            text = str(arg)
            if text == "42S02" or text.startswith("42S02"):
                return True
            if re.search(r"(^|[^0-9])200753([^0-9]|$)", text):
                return True
            if "42S02" in text:
                return True
        return False

    def _parse_int(self, value, name):
        try:
            return int(value)
        except (TypeError, ValueError):
            raise ValueError("Invalid integer for '%s': %r" % (name, value))

    def _parse_float(self, value, name):
        try:
            return float(value)
        except (TypeError, ValueError):
            raise ValueError("Invalid float for '%s': %r" % (name, value))

    def _parse_bool(self, value, name):
        if isinstance(value, bool):
            return value
        if isinstance(value, int):
            if value in (0, 1):
                return bool(value)
            raise ValueError("Invalid boolean for '%s': %r" % (name, value))

        lowered = str(value).strip().lower()
        if lowered in AltibaseDriver.TRUE_VALUES:
            return True
        if lowered in AltibaseDriver.FALSE_VALUES:
            return False
        raise ValueError("Invalid boolean for '%s': %r" % (name, value))

    def loadTuples(self, tableName, tuples):
        if len(tuples) == 0:
            return

        if hasattr(self.cursor, "fast_executemany"):
            self.cursor.fast_executemany = self.fast_executemany

        placeholders = ",".join(["?"] * len(tuples[0]))
        sql = "INSERT INTO %s VALUES (%s)" % (tableName, placeholders)
        self.cursor.executemany(sql, tuples)
        logging.debug("Loaded %d tuples for tableName %s" % (len(tuples), tableName))

    def loadFinish(self):
        logging.debug("Committing Altibase load changes")
        self.conn.commit()

    def cleanup(self):
        if self.cursor is not None:
            try:
                self.cursor.close()
            except Exception:
                logging.debug("Ignoring error while closing Altibase cursor", exc_info=True)
            finally:
                self.cursor = None

        if self.conn is not None:
            try:
                self.conn.close()
            except Exception:
                logging.debug("Ignoring error while closing Altibase connection", exc_info=True)
            finally:
                self.conn = None

    def getNumberWH(self):
        self.cursor.execute("SELECT MAX(W_ID) FROM WAREHOUSE")
        return self.cursor.fetchone()[0]
