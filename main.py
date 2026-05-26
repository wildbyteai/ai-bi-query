import json
from decimal import Decimal
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, StreamingResponse
from pydantic import BaseModel
from engine.schema_loader import load_schema, list_tables, list_tables_text, get_valid_table_names
from engine.llm_client import get_client
from engine import nl2sql, sql_executor


class DecimalEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, Decimal):
            return float(obj)
        return super().default(obj)


def sse_event(event: str, data) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False, cls=DecimalEncoder)}\n\n"


app = FastAPI(title="AI BI 问数")


class AskRequest(BaseModel):
    question: str
    table_filter: list[str] | None = None
    history: list[dict] | None = None


@app.post("/api/ask")
def ask(req: AskRequest):
    return nl2sql.ask(req.question, req.table_filter, req.history)


@app.post("/api/ask/stream")
def ask_stream(req: AskRequest):
    def generate():
        client = get_client()
        question = req.question
        history = req.history or []

        # 多轮对话上下文
        if history:
            context_parts = []
            for h in history[-3:]:
                context_parts.append(f"问题：{h['q']}\nSQL：{h['sql']}")
            context = "\n---\n".join(context_parts)
            full_question = f"之前的对话：\n{context}\n\n当前问题：{question}"
        else:
            full_question = question

        # Step 1: 选表
        yield sse_event("step", {"text": "正在分析问题，选择相关数据表...", "id": "select"})

        if req.table_filter:
            selected = req.table_filter
        else:
            selected = nl2sql.select_tables(full_question, client)

        if not selected:
            yield sse_event("error", {"text": "无法确定相关的数据表，请换个问法"})
            return

        yield sse_event("tables", {"tables": selected})

        # Step 2: 读取 schema
        yield sse_event("step", {"text": f"正在读取 {len(selected)} 张表的结构...", "id": "schema"})
        schema = load_schema(selected)
        yield sse_event("schema_done", {"text": "表结构读取完成"})

        # Step 3: 生成 SQL
        yield sse_event("step", {"text": "正在生成 SQL...", "id": "sql"})
        sql = nl2sql.generate_sql(question, schema, client)

        if not sql or sql.startswith("ERROR"):
            yield sse_event("error", {"text": sql or "LLM 未能生成 SQL"})
            return

        yield sse_event("sql", {"sql": sql})

        # Step 4: 执行查询
        yield sse_event("step", {"text": "正在执行查询...", "id": "exec"})
        try:
            result = sql_executor.execute(sql)
        except Exception as e:
            # 重试
            yield sse_event("step", {"text": f"查询出错，正在重试... ({str(e)[:50]})", "id": "retry"})
            sql2 = nl2sql.generate_sql(question, schema, client, error_hint=f"{str(e)}\n请仔细对照 schema，确保列名正确。")
            yield sse_event("sql", {"sql": sql2, "retry": True})
            try:
                result = sql_executor.execute(sql2)
                sql = sql2
            except Exception as e2:
                yield sse_event("error", {"text": str(e2), "sql": sql2})
                return

        yield sse_event("result", {
            "columns": result["columns"],
            "rows": result["rows"][:50],
            "row_count": result["row_count"],
        })

        # Step 5: 总结
        yield sse_event("step", {"text": "正在分析结果...", "id": "summary"})
        summary = nl2sql.summarize(question, sql, result, client)
        yield sse_event("summary", {"text": summary})

        # 完成
        yield sse_event("done", {
            "sql": sql,
            "tables": selected,
            "row_count": result["row_count"],
        })

    return StreamingResponse(generate(), media_type="text/event-stream")


@app.get("/api/schema")
def schema():
    tables = list_tables()
    return {"tables": tables, "count": len(tables)}


@app.get("/api/reports")
def reports():
    with open("frontend/report_directory.json", encoding="utf-8") as f:
        return json.load(f)


@app.get("/api/sql-definitions")
def sql_definitions():
    with open("frontend/sql_definitions.json", encoding="utf-8") as f:
        return json.load(f)


app.mount("/static", StaticFiles(directory="frontend"), name="static")


@app.get("/", response_class=HTMLResponse)
def index():
    with open("frontend/index.html", encoding="utf-8") as f:
        return f.read()
