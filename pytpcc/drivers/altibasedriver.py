# -*- coding: utf-8 -*-

from decimal import Decimal
import logging
import os
import re
from pprint import pformat
from time import sleep

try:
    import constants
except ImportError:
    from .. import constants

from .abstractdriver import AbstractDriver


TXN_QUERIES = {
    "DELIVERY": {
        "getNewOrder": "SELECT NO_O_ID FROM NEW_ORDER WHERE NO_D_ID = ? AND NO_W_ID = ? AND NO_O_ID > -1 ORDER BY NO_O_ID LIMIT 1",
        "deleteNewOrder": "DELETE FROM NEW_ORDER WHERE NO_D_ID = ? AND NO_W_ID = ? AND NO_O_ID = ?",
        "getCId": "SELECT O_C_ID FROM ORDERS WHERE O_ID = ? AND O_D_ID = ? AND O_W_ID = ?",
        "updateOrders": "UPDATE ORDERS SET O_CARRIER_ID = ? WHERE O_ID = ? AND O_D_ID = ? AND O_W_ID = ?",
        "updateOrderLine": "UPDATE ORDER_LINE SET OL_DELIVERY_D = ? WHERE OL_O_ID = ? AND OL_D_ID = ? AND OL_W_ID = ?",
        "sumOLAmount": "SELECT SUM(OL_AMOUNT) FROM ORDER_LINE WHERE OL_O_ID = ? AND OL_D_ID = ? AND OL_W_ID = ?",
        "updateCustomer": "UPDATE CUSTOMER SET C_BALANCE = C_BALANCE + ? WHERE C_ID = ? AND C_D_ID = ? AND C_W_ID = ?",
    },
    "NEW_ORDER": {
        "getWarehouseTaxRate": "SELECT W_TAX FROM WAREHOUSE WHERE W_ID = ?",
        "getDistrict": "SELECT D_TAX, D_NEXT_O_ID FROM DISTRICT WHERE D_ID = ? AND D_W_ID = ?",
        "incrementNextOrderId": "UPDATE DISTRICT SET D_NEXT_O_ID = ? WHERE D_ID = ? AND D_W_ID = ?",
        "getCustomer": "SELECT C_DISCOUNT, C_LAST, C_CREDIT FROM CUSTOMER WHERE C_W_ID = ? AND C_D_ID = ? AND C_ID = ?",
        "createOrder": "INSERT INTO ORDERS (O_ID, O_D_ID, O_W_ID, O_C_ID, O_ENTRY_D, O_CARRIER_ID, O_OL_CNT, O_ALL_LOCAL) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        "createNewOrder": "INSERT INTO NEW_ORDER (NO_O_ID, NO_D_ID, NO_W_ID) VALUES (?, ?, ?)",
        "getItemInfo": "SELECT I_PRICE, I_NAME, I_DATA FROM ITEM WHERE I_ID = ?",
        "getStockInfo": "SELECT S_QUANTITY, S_DATA, S_YTD, S_ORDER_CNT, S_REMOTE_CNT, S_DIST_{:02d} FROM STOCK WHERE S_I_ID = ? AND S_W_ID = ?",
        "updateStock": "UPDATE STOCK SET S_QUANTITY = ?, S_YTD = ?, S_ORDER_CNT = ?, S_REMOTE_CNT = ? WHERE S_I_ID = ? AND S_W_ID = ?",
        "createOrderLine": "INSERT INTO ORDER_LINE (OL_O_ID, OL_D_ID, OL_W_ID, OL_NUMBER, OL_I_ID, OL_SUPPLY_W_ID, OL_DELIVERY_D, OL_QUANTITY, OL_AMOUNT, OL_DIST_INFO) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
    },
    "ORDER_STATUS": {
        "getCustomerByCustomerId": "SELECT C_ID, C_FIRST, C_MIDDLE, C_LAST, C_BALANCE FROM CUSTOMER WHERE C_W_ID = ? AND C_D_ID = ? AND C_ID = ?",
        "getCustomersByLastName": "SELECT C_ID, C_FIRST, C_MIDDLE, C_LAST, C_BALANCE FROM CUSTOMER WHERE C_W_ID = ? AND C_D_ID = ? AND C_LAST = ? ORDER BY C_FIRST",
        "getLastOrder": "SELECT O_ID, O_CARRIER_ID, O_ENTRY_D FROM ORDERS WHERE O_W_ID = ? AND O_D_ID = ? AND O_C_ID = ? ORDER BY O_ID DESC LIMIT 1",
        "getOrderLines": "SELECT OL_SUPPLY_W_ID, OL_I_ID, OL_QUANTITY, OL_AMOUNT, OL_DELIVERY_D FROM ORDER_LINE WHERE OL_W_ID = ? AND OL_D_ID = ? AND OL_O_ID = ?",
    },
    "PAYMENT": {
        "getWarehouse": "SELECT W_NAME, W_STREET_1, W_STREET_2, W_CITY, W_STATE, W_ZIP FROM WAREHOUSE WHERE W_ID = ?",
        "updateWarehouseBalance": "UPDATE WAREHOUSE SET W_YTD = W_YTD + ? WHERE W_ID = ?",
        "getDistrict": "SELECT D_NAME, D_STREET_1, D_STREET_2, D_CITY, D_STATE, D_ZIP FROM DISTRICT WHERE D_W_ID = ? AND D_ID = ?",
        "updateDistrictBalance": "UPDATE DISTRICT SET D_YTD = D_YTD + ? WHERE D_W_ID = ? AND D_ID = ?",
        "getCustomerByCustomerId": "SELECT C_ID, C_FIRST, C_MIDDLE, C_LAST, C_STREET_1, C_STREET_2, C_CITY, C_STATE, C_ZIP, C_PHONE, C_SINCE, C_CREDIT, C_CREDIT_LIM, C_DISCOUNT, C_BALANCE, C_YTD_PAYMENT, C_PAYMENT_CNT, C_DATA FROM CUSTOMER WHERE C_W_ID = ? AND C_D_ID = ? AND C_ID = ?",
        "getCustomersByLastName": "SELECT C_ID, C_FIRST, C_MIDDLE, C_LAST, C_STREET_1, C_STREET_2, C_CITY, C_STATE, C_ZIP, C_PHONE, C_SINCE, C_CREDIT, C_CREDIT_LIM, C_DISCOUNT, C_BALANCE, C_YTD_PAYMENT, C_PAYMENT_CNT, C_DATA FROM CUSTOMER WHERE C_W_ID = ? AND C_D_ID = ? AND C_LAST = ? ORDER BY C_FIRST",
        "updateBCCustomer": "UPDATE CUSTOMER SET C_BALANCE = ?, C_YTD_PAYMENT = ?, C_PAYMENT_CNT = ?, C_DATA = ? WHERE C_W_ID = ? AND C_D_ID = ? AND C_ID = ?",
        "updateGCCustomer": "UPDATE CUSTOMER SET C_BALANCE = ?, C_YTD_PAYMENT = ?, C_PAYMENT_CNT = ? WHERE C_W_ID = ? AND C_D_ID = ? AND C_ID = ?",
        "insertHistory": "INSERT INTO HISTORY VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
    },
    "STOCK_LEVEL": {
        "getOId": "SELECT D_NEXT_O_ID FROM DISTRICT WHERE D_W_ID = ? AND D_ID = ?",
        "getStockCount": """
            SELECT COUNT(DISTINCT OL_I_ID) FROM ORDER_LINE, STOCK
            WHERE OL_W_ID = ?
              AND OL_D_ID = ?
              AND OL_O_ID < ?
              AND OL_O_ID >= ?
              AND S_W_ID = ?
              AND S_I_ID = OL_I_ID
              AND S_QUANTITY < ?
        """,
    },
}


class AltibaseDriver(AbstractDriver):
    DEFAULT_CONFIG = {
        "backend": ("The Altibase connection backend: pyodbc or native", "pyodbc"),
        "dsn": ("The Altibase ODBC DSN for backend=pyodbc", "ALTIBASE_LOCAL"),
        "host": ("The Altibase host for backend=native", "127.0.0.1"),
        "port-env": ("The environment variable containing the Altibase port for backend=native", "ALTIBASE_PORT_NO"),
        "user": ("The username to connect to Altibase", "PYTPCC"),
        "password": ("The password to connect to Altibase", "PYTPCC"),
        "nls-use": ("The Altibase NLS_USE value for backend=native", "US7ASCII"),
        "connection-timeout": ("The pyodbc connection timeout in seconds for backend=pyodbc", "5"),
        "connect-timeout": ("The native driver connect timeout in seconds for backend=native", "5"),
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
    DETERMINISTIC_EXCEPTION_TYPES = (AssertionError, AttributeError, IndexError, KeyError, TypeError, ValueError)
    DETERMINISTIC_DBAPI_EXCEPTION_NAMES = set(["DataError", "IntegrityError", "InterfaceError", "NotSupportedError", "ProgrammingError"])
    DETERMINISTIC_SQLSTATE_PREFIXES = ("07", "21", "22", "23", "42")
    DETERMINISTIC_SQLSTATES = set(["HY004", "HY024", "HYC00", "IM001", "IM002"])
    DETERMINISTIC_MESSAGE_PATTERNS = [
        "syntax",
        "conversion",
        "convert",
        "data type",
        "invalid character",
        "invalid identifier",
        "invalid column",
        "invalid table",
        "not found",
        "does not exist",
        "duplicate",
        "unique",
        "constraint",
    ]

    def __init__(self, ddl):
        super(AltibaseDriver, self).__init__("altibase", ddl)
        self.conn = None
        self.cursor = None
        self.backend = None
        self.dsn = None
        self.host = None
        self.port_env = None
        self.native_port = None
        self.user = None
        self.password = None
        self.nls_use = None
        self.connection_timeout = None
        self.connect_timeout = None
        self.max_retries = None
        self.retry_delay = None
        self.fast_executemany = None

    def makeDefaultConfig(self):
        return AltibaseDriver.DEFAULT_CONFIG

    def loadConfig(self, config):
        config = self._config_with_defaults(config)

        self.backend = str(config["backend"]).strip().lower()
        if self.backend not in ("pyodbc", "native"):
            raise ValueError("Invalid Altibase backend %r; expected 'pyodbc' or 'native'" % (config["backend"],))

        self.user = str(config["user"])
        self.password = str(config["password"])
        self.max_retries = self._parse_int(config["max-retries"], "max-retries")
        self.retry_delay = self._parse_float(config["retry-delay"], "retry-delay")
        if self.max_retries < 0:
            raise ValueError("Invalid integer for 'max-retries': %r" % (self.max_retries,))
        if self.retry_delay < 0:
            raise ValueError("Invalid float for 'retry-delay': %r" % (self.retry_delay,))

        if self.backend == "pyodbc":
            self.dsn = str(config["dsn"])
            self.connection_timeout = self._parse_int(config["connection-timeout"], "connection-timeout")
            self.fast_executemany = self._parse_bool(config["fast-executemany"], "fast-executemany")
        else:
            self.host = str(config["host"]).strip()
            self.port_env = str(config["port-env"]).strip()
            self.native_port = self._read_native_port(self.port_env)
            self.nls_use = str(config["nls-use"]).strip()
            self.connect_timeout = self._parse_int(config["connect-timeout"], "connect-timeout")
            self.fast_executemany = False

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

    def _config_with_defaults(self, config):
        resolved = dict((key, value[1]) for key, value in AltibaseDriver.DEFAULT_CONFIG.items())
        resolved.update(config)
        return resolved

    def _connect(self):
        if self.backend == "native":
            return self._connect_native()
        return self._connect_pyodbc()

    def _connect_pyodbc(self):
        try:
            import pyodbc
        except ImportError as ex:
            raise ImportError("AltibaseDriver backend=pyodbc requires pyodbc to connect. Install pyodbc or choose backend=native.") from ex

        connection_string = "DSN=%s;UID=%s;PWD=%s" % (self.dsn, self.user, self.password)
        logging.debug("Connecting to Altibase DSN '%s' as user '%s'", self.dsn, self.user)
        return pyodbc.connect(connection_string, timeout=self.connection_timeout)

    def _connect_native(self):
        try:
            import altibase
        except ImportError as ex:
            raise ImportError(
                "AltibaseDriver backend=native requires the altibase package. "
                "Set PYTHONPATH=/home/et16/work/altibase-python-driver/src or install the package."
            ) from ex

        options = {
            "host": self.host,
            "port": self.native_port,
            "user": self.user,
            "password": self.password,
            "connect_timeout": self.connect_timeout,
        }
        if self.nls_use:
            options["nls_use"] = self.nls_use

        logging.debug(
            "Connecting to Altibase native host '%s' port %d as user '%s' nls-use '%s'",
            self.host,
            self.native_port,
            self.user,
            self.nls_use or "",
        )
        return altibase.connect(**options)

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
        if "42S02" in self._extract_sqlstates(ex):
            return True
        if 200753 in self._extract_vendor_codes(ex):
            return True
        message = " ".join(str(arg) for arg in getattr(ex, "args", [ex]))
        if "42S02" in message or re.search(r"(^|[^0-9])200753([^0-9]|$)", message):
            return True
        return False

    def _read_native_port(self, env_name):
        if not env_name:
            raise ValueError("Altibase backend=native requires a non-empty 'port-env' setting")
        value = os.environ.get(env_name)
        if value is None or str(value).strip() == "":
            raise ValueError(
                "Altibase backend=native requires environment variable '%s' to contain the TCP port" % env_name
            )
        port = self._parse_int(value, env_name)
        if port <= 0 or port > 65535:
            raise ValueError("Invalid TCP port in '%s': %r" % (env_name, value))
        return port

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

    def _fetchone_required(self, description):
        row = self.cursor.fetchone()
        assert row is not None, "Missing %s" % description
        return row

    def _median_customer(self, customers, description):
        customers = customers or []
        assert len(customers) > 0, "No matching customer for %s" % description
        return customers[(len(customers) - 1) // 2]

    def _match_numeric_type(self, reference, value):
        if isinstance(reference, Decimal) and not isinstance(value, Decimal):
            return Decimal(str(value))
        return value

    def _handle_transaction_exception(self, txn_name, ex, retries):
        try:
            self.conn.rollback()
        except Exception:
            logging.exception("Altibase %s rollback failed after transaction error", txn_name)

        sqlstates = self._extract_sqlstates(ex)
        vendor_codes = self._extract_vendor_codes(ex)
        deterministic = self._is_deterministic_error(ex, sqlstates)
        logging.warning(
            "Altibase %s failed after %d retries; deterministic=%s; %s: %s",
            txn_name,
            retries,
            deterministic,
            self._format_exception_details(ex, sqlstates, vendor_codes),
            ex,
        )

        if deterministic:
            raise ex
        if retries >= self.max_retries:
            logging.error("Altibase %s exceeded max-retries=%d", txn_name, self.max_retries)
            raise ex

        retries += 1
        if self.retry_delay > 0:
            sleep(retries * self.retry_delay)
        return retries

    def _format_exception_details(self, ex, sqlstates, vendor_codes):
        details = []
        if sqlstates:
            details.append("SQLSTATE=%s" % ",".join(sqlstates))
        if vendor_codes:
            details.append("vendor=%s" % ",".join(str(code) for code in vendor_codes))
        diagnostic_records = self._diagnostic_records(ex)
        if diagnostic_records:
            details.append("diagnostic-records=%d" % len(diagnostic_records))
        return "; ".join(details) if details else "no SQL diagnostics"

    def _extract_sqlstates(self, ex):
        sqlstates = []
        for attr in ("sqlstate", "sql_state", "SQLSTATE"):
            self._append_sqlstate(sqlstates, getattr(ex, attr, None))
        for record in self._diagnostic_records(ex):
            for key, value in record.items():
                if str(key).lower() in ("sqlstate", "sql_state"):
                    self._append_sqlstate(sqlstates, value)
        for arg in getattr(ex, "args", []):
            text = str(arg).upper()
            for state in re.findall(r"\b([0-9A-Z]{5})\b", text):
                self._append_sqlstate(sqlstates, state)
        return sqlstates

    def _extract_vendor_codes(self, ex):
        codes = []
        for attr in ("vendor_code", "code", "native_code", "error_code"):
            self._append_vendor_code(codes, getattr(ex, attr, None))
        for record in self._diagnostic_records(ex):
            for key, value in record.items():
                if str(key).lower() in ("vendor_code", "code", "native_code", "error_code"):
                    self._append_vendor_code(codes, value)
        for arg in getattr(ex, "args", []):
            self._append_vendor_code(codes, arg)
        return codes

    def _append_sqlstate(self, sqlstates, value):
        if value is None:
            return
        state = str(value).strip().upper()
        if not re.match(r"^[0-9A-Z]{5}$", state):
            return
        if not (state[:2].isdigit() or state.startswith("HY") or state.startswith("IM")):
            return
        if state not in sqlstates:
            sqlstates.append(state)

    def _append_vendor_code(self, codes, value):
        if value is None or isinstance(value, bool):
            return
        if isinstance(value, int):
            code = value
        else:
            text = str(value).strip()
            if re.match(r"^-?\d+$", text):
                code = int(text)
            else:
                for match in re.findall(r"\((-?\d{5,})\)", text):
                    self._append_vendor_code(codes, int(match))
                return
        if code not in codes:
            codes.append(code)

    def _diagnostic_records(self, ex):
        records = getattr(ex, "diagnostic_records", None)
        if records is None:
            return []
        if isinstance(records, dict):
            return [records]
        try:
            return [record for record in records if isinstance(record, dict)]
        except TypeError:
            return []

    def _is_deterministic_error(self, ex, sqlstates):
        if isinstance(ex, AltibaseDriver.DETERMINISTIC_EXCEPTION_TYPES):
            return True
        if ex.__class__.__name__ in AltibaseDriver.DETERMINISTIC_DBAPI_EXCEPTION_NAMES:
            return True
        for state in sqlstates:
            if state in AltibaseDriver.DETERMINISTIC_SQLSTATES:
                return True
            if state[:2] in AltibaseDriver.DETERMINISTIC_SQLSTATE_PREFIXES:
                return True
        message = " ".join(str(arg).lower() for arg in getattr(ex, "args", [ex]))
        for pattern in AltibaseDriver.DETERMINISTIC_MESSAGE_PATTERNS:
            if pattern in message:
                return True
        return False

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

    def doDelivery(self, params):
        retries = 0
        q = TXN_QUERIES["DELIVERY"]

        w_id = params["w_id"]
        o_carrier_id = params["o_carrier_id"]
        ol_delivery_d = params["ol_delivery_d"]

        while True:
            try:
                result = []
                for d_id in range(1, constants.DISTRICTS_PER_WAREHOUSE + 1):
                    self.cursor.execute(q["getNewOrder"], [d_id, w_id])
                    new_order = self.cursor.fetchone()
                    if new_order is None:
                        continue
                    no_o_id = new_order[0]

                    self.cursor.execute(q["getCId"], [no_o_id, d_id, w_id])
                    c_id = self._fetchone_required("ORDERS customer for delivery")[0]

                    self.cursor.execute(q["sumOLAmount"], [no_o_id, d_id, w_id])
                    ol_total = self._fetchone_required("ORDER_LINE total for delivery")[0]
                    assert ol_total is not None, "ol_total is NULL for delivery order %s/%s/%s" % (w_id, d_id, no_o_id)
                    assert ol_total > 0.0

                    self.cursor.execute(q["deleteNewOrder"], [d_id, w_id, no_o_id])
                    self.cursor.execute(q["updateOrders"], [o_carrier_id, no_o_id, d_id, w_id])
                    self.cursor.execute(q["updateOrderLine"], [ol_delivery_d, no_o_id, d_id, w_id])
                    self.cursor.execute(q["updateCustomer"], [ol_total, c_id, d_id, w_id])

                    result.append((d_id, no_o_id))

                self.conn.commit()
                return (result, retries)
            except Exception as ex:
                retries = self._handle_transaction_exception("DELIVERY", ex, retries)

    def doNewOrder(self, params):
        q = TXN_QUERIES["NEW_ORDER"]
        retries = 0

        w_id = params["w_id"]
        d_id = params["d_id"]
        c_id = params["c_id"]
        o_entry_d = params["o_entry_d"]
        i_ids = params["i_ids"]
        i_w_ids = params["i_w_ids"]
        i_qtys = params["i_qtys"]

        assert len(i_ids) > 0
        assert len(i_ids) == len(i_w_ids)
        assert len(i_ids) == len(i_qtys)

        while True:
            try:
                all_local = True
                items = []
                item_data = []
                total = 0

                for i in range(len(i_ids)):
                    all_local = all_local and i_w_ids[i] == w_id
                    self.cursor.execute(q["getItemInfo"], [i_ids[i]])
                    items.append(self.cursor.fetchone())
                assert len(items) == len(i_ids)

                for item in items:
                    if item is None:
                        self.conn.rollback()
                        return (None, retries)

                self.cursor.execute(q["getWarehouseTaxRate"], [w_id])
                w_tax = self._fetchone_required("WAREHOUSE tax for new order")[0]

                self.cursor.execute(q["getDistrict"], [d_id, w_id])
                district_info = self._fetchone_required("DISTRICT row for new order")
                d_tax = district_info[0]
                d_next_o_id = district_info[1]

                self.cursor.execute(q["getCustomer"], [w_id, d_id, c_id])
                customer_info = self._fetchone_required("CUSTOMER row for new order")
                c_discount = customer_info[0]

                ol_cnt = len(i_ids)
                o_carrier_id = constants.NULL_CARRIER_ID
                o_all_local = 1 if all_local else 0

                self.cursor.execute(q["incrementNextOrderId"], [d_next_o_id + 1, d_id, w_id])
                self.cursor.execute(q["createOrder"], [d_next_o_id, d_id, w_id, c_id, o_entry_d, o_carrier_id, ol_cnt, o_all_local])
                self.cursor.execute(q["createNewOrder"], [d_next_o_id, d_id, w_id])

                for i in range(len(i_ids)):
                    ol_number = i + 1
                    ol_supply_w_id = i_w_ids[i]
                    ol_i_id = i_ids[i]
                    ol_quantity = i_qtys[i]

                    item_info = items[i]
                    i_price = item_info[0]
                    i_name = item_info[1]
                    i_data = item_info[2]

                    self.cursor.execute(q["getStockInfo"].format(d_id), [ol_i_id, ol_supply_w_id])
                    stock_info = self._fetchone_required("STOCK row for new order")
                    s_quantity = stock_info[0]
                    s_data = stock_info[1]
                    s_ytd = stock_info[2]
                    s_order_cnt = stock_info[3]
                    s_remote_cnt = stock_info[4]
                    s_dist_xx = stock_info[5]

                    s_ytd += ol_quantity
                    if s_quantity >= ol_quantity + 10:
                        s_quantity -= ol_quantity
                    else:
                        s_quantity = s_quantity + 91 - ol_quantity
                    s_order_cnt += 1
                    if ol_supply_w_id != w_id:
                        s_remote_cnt += 1

                    self.cursor.execute(q["updateStock"], [s_quantity, s_ytd, s_order_cnt, s_remote_cnt, ol_i_id, ol_supply_w_id])

                    if i_data.find(constants.ORIGINAL_STRING) != -1 and s_data.find(constants.ORIGINAL_STRING) != -1:
                        brand_generic = "B"
                    else:
                        brand_generic = "G"

                    ol_amount = ol_quantity * i_price
                    total += ol_amount

                    self.cursor.execute(q["createOrderLine"], [d_next_o_id, d_id, w_id, ol_number, ol_i_id, ol_supply_w_id, o_entry_d, ol_quantity, ol_amount, s_dist_xx])
                    item_data.append((i_name, s_quantity, brand_generic, i_price, ol_amount))

                total *= (1 - c_discount) * (1 + w_tax + d_tax)
                misc = [(w_tax, d_tax, d_next_o_id, total)]

                self.conn.commit()
                return ([customer_info, misc, item_data], retries)
            except Exception as ex:
                retries = self._handle_transaction_exception("NEW_ORDER", ex, retries)

    def doOrderStatus(self, params):
        q = TXN_QUERIES["ORDER_STATUS"]
        retries = 0

        w_id = params["w_id"]
        d_id = params["d_id"]
        c_id = params["c_id"]
        c_last = params["c_last"]

        assert w_id, pformat(params)
        assert d_id, pformat(params)

        while True:
            try:
                selected_c_id = c_id
                if c_id is not None:
                    self.cursor.execute(q["getCustomerByCustomerId"], [w_id, d_id, c_id])
                    customer = self._fetchone_required("CUSTOMER row for order status")
                else:
                    self.cursor.execute(q["getCustomersByLastName"], [w_id, d_id, c_last])
                    customer = self._median_customer(self.cursor.fetchall(), "order status last name %s" % c_last)
                    selected_c_id = customer[0]
                assert selected_c_id is not None

                self.cursor.execute(q["getLastOrder"], [w_id, d_id, selected_c_id])
                order = self.cursor.fetchone()
                if order is not None:
                    self.cursor.execute(q["getOrderLines"], [w_id, d_id, order[0]])
                    order_lines = self.cursor.fetchall() or []
                else:
                    order_lines = []

                self.conn.commit()
                return ([customer, order, order_lines], retries)
            except Exception as ex:
                retries = self._handle_transaction_exception("ORDER_STATUS", ex, retries)

    def doPayment(self, params):
        q = TXN_QUERIES["PAYMENT"]
        retries = 0

        w_id = params["w_id"]
        d_id = params["d_id"]
        h_amount = params["h_amount"]
        c_w_id = params["c_w_id"]
        c_d_id = params["c_d_id"]
        c_id = params["c_id"]
        c_last = params["c_last"]
        h_date = params["h_date"]

        while True:
            try:
                selected_c_id = c_id
                if c_id is not None:
                    self.cursor.execute(q["getCustomerByCustomerId"], [c_w_id, c_d_id, c_id])
                    customer = self._fetchone_required("CUSTOMER row for payment")
                else:
                    self.cursor.execute(q["getCustomersByLastName"], [c_w_id, c_d_id, c_last])
                    customer = self._median_customer(self.cursor.fetchall(), "payment last name %s" % c_last)
                    selected_c_id = customer[0]
                assert selected_c_id is not None

                h_amount_db = self._match_numeric_type(customer[14], h_amount)
                c_balance = customer[14] - h_amount_db
                c_ytd_payment = customer[15] + self._match_numeric_type(customer[15], h_amount)
                c_payment_cnt = customer[16] + 1
                c_data = customer[17]

                self.cursor.execute(q["getWarehouse"], [w_id])
                warehouse = self._fetchone_required("WAREHOUSE row for payment")

                self.cursor.execute(q["getDistrict"], [w_id, d_id])
                district = self._fetchone_required("DISTRICT row for payment")

                self.cursor.execute(q["updateWarehouseBalance"], [h_amount_db, w_id])
                self.cursor.execute(q["updateDistrictBalance"], [h_amount_db, w_id, d_id])

                if customer[11] == constants.BAD_CREDIT:
                    new_data = " ".join(map(str, [selected_c_id, c_d_id, c_w_id, d_id, w_id, h_amount]))
                    c_data = new_data + "|" + c_data
                    if len(c_data) > constants.MAX_C_DATA:
                        c_data = c_data[:constants.MAX_C_DATA]
                    self.cursor.execute(q["updateBCCustomer"], [c_balance, c_ytd_payment, c_payment_cnt, c_data, c_w_id, c_d_id, selected_c_id])
                else:
                    c_data = ""
                    self.cursor.execute(q["updateGCCustomer"], [c_balance, c_ytd_payment, c_payment_cnt, c_w_id, c_d_id, selected_c_id])

                h_data = "%s    %s" % (warehouse[0], district[0])
                self.cursor.execute(q["insertHistory"], [selected_c_id, c_d_id, c_w_id, d_id, w_id, h_date, h_amount_db, h_data])

                self.conn.commit()
                return ([warehouse, district, customer], retries)
            except Exception as ex:
                retries = self._handle_transaction_exception("PAYMENT", ex, retries)

    def doStockLevel(self, params):
        q = TXN_QUERIES["STOCK_LEVEL"]
        retries = 0

        w_id = params["w_id"]
        d_id = params["d_id"]
        threshold = params["threshold"]

        while True:
            try:
                self.cursor.execute(q["getOId"], [w_id, d_id])
                o_id = self._fetchone_required("DISTRICT next order id for stock level")[0]

                self.cursor.execute(q["getStockCount"], [w_id, d_id, o_id, (o_id - 20), w_id, threshold])
                stock_count = self._fetchone_required("STOCK_LEVEL count")[0]

                self.conn.commit()
                return (int(stock_count), retries)
            except Exception as ex:
                retries = self._handle_transaction_exception("STOCK_LEVEL", ex, retries)
