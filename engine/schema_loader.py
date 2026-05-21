import time
import pymysql
import config

_cache = {"tables": None, "ts": 0}
CACHE_TTL = 300  # 5 分钟


def get_connection(db=None):
    return pymysql.connect(
        host=config.DB_HOST,
        port=config.DB_PORT,
        user=config.DB_USER,
        password=config.DB_PASS,
        database=db or config.DB_NAME,
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
        connect_timeout=5,
        read_timeout=10,
    )


def _fetch_tables():
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT TABLE_NAME, TABLE_COMMENT
                FROM INFORMATION_SCHEMA.TABLES
                WHERE TABLE_SCHEMA = %s AND TABLE_TYPE = 'BASE TABLE'
                ORDER BY TABLE_NAME
                """,
                (config.DB_NAME,),
            )
            return cur.fetchall()
    finally:
        conn.close()


def _fetch_columns(tname):
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT COLUMN_NAME, COLUMN_TYPE, COLUMN_COMMENT, IS_NULLABLE,
                       COLUMN_KEY, COLUMN_DEFAULT
                FROM INFORMATION_SCHEMA.COLUMNS
                WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s
                ORDER BY ORDINAL_POSITION
                """,
                (config.DB_NAME, tname),
            )
            return cur.fetchall()
    finally:
        conn.close()


def _get_tables():
    now = time.time()
    if _cache["tables"] and now - _cache["ts"] < CACHE_TTL:
        return _cache["tables"]
    tables = _fetch_tables()
    _cache["tables"] = tables
    _cache["ts"] = now
    return tables


def load_schema(table_filter=None):
    """加载选中表的完整 schema。"""
    all_tables = _get_tables()

    # 构建有效表名集合（用于验证）
    valid_names = {t["TABLE_NAME"] for t in all_tables}

    schema = []
    for t in all_tables:
        tname = t["TABLE_NAME"]
        if table_filter:
            # 精确匹配或包含匹配
            matched = False
            for f in table_filter:
                if f == tname or f in tname:
                    matched = True
                    break
            if not matched:
                continue

        columns = _fetch_columns(tname)
        cols = []
        for c in columns:
            desc = c["COLUMN_NAME"] + " " + c["COLUMN_TYPE"]
            if c["COLUMN_COMMENT"]:
                desc += f" -- {c['COLUMN_COMMENT']}"
            if c["COLUMN_KEY"] == "PRI":
                desc += " [PK]"
            cols.append(desc)

        table_desc = f"## 表 {tname}"
        if t["TABLE_COMMENT"]:
            table_desc += f" ({t['TABLE_COMMENT']})"
        table_desc += "\n" + "\n".join(f"  - {col}" for col in cols)
        schema.append(table_desc)

    return "\n\n".join(schema)


def list_tables():
    """返回所有表名 + 注释。"""
    return _get_tables()


def list_tables_text():
    """返回所有表名 + 注释的纯文本。"""
    tables = _get_tables()
    lines = []
    for t in tables:
        name = t["TABLE_NAME"]
        comment = t.get("TABLE_COMMENT", "")
        if comment:
            lines.append(f"{name} -- {comment}")
        else:
            lines.append(name)
    return "\n".join(lines)


def get_valid_table_names():
    """返回所有有效表名集合，用于验证。"""
    return {t["TABLE_NAME"] for t in _get_tables()}
