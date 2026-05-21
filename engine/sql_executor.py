import re
import pymysql
import config

FORBIDDEN = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|TRUNCATE|CREATE|GRANT|REVOKE|EXEC)\b",
    re.IGNORECASE,
)


def validate_sql(sql: str) -> str:
    """校验 SQL 安全性，返回清洗后的 SQL。"""
    sql = sql.strip().rstrip(";")
    if not sql.upper().startswith("SELECT"):
        raise ValueError("只允许 SELECT 查询")
    if FORBIDDEN.search(sql):
        raise ValueError("包含禁止的关键字")
    # 强制加 LIMIT
    if "LIMIT" not in sql.upper():
        sql += " LIMIT 100"
    return sql


def execute(sql: str) -> dict:
    """执行 SQL，返回 {columns, rows, row_count}。"""
    sql = validate_sql(sql)
    conn = pymysql.connect(
        host=config.DB_HOST,
        port=config.DB_PORT,
        user=config.DB_USER,
        password=config.DB_PASS,
        database=config.DB_NAME,
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
        connect_timeout=5,
        read_timeout=10,
    )
    try:
        with conn.cursor() as cur:
            cur.execute(sql)
            rows = cur.fetchall()
            columns = [desc[0] for desc in cur.description] if cur.description else []
        return {
            "columns": columns,
            "rows": rows,
            "row_count": len(rows),
        }
    finally:
        conn.close()
