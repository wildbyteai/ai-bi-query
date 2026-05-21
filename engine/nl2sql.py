from engine.schema_loader import load_schema, list_tables_text, get_valid_table_names
from engine.llm_client import get_client
from engine import sql_executor

# 业务词典：常见概念 → 相关表
BIZ_HINT = """
业务概念与表的对应关系（选表参考）：
- 回款/到款 → imp_money, imp_money_bcompany, imp_money_cloud, mid_finance_returned_money
- 出货/发货/销售额 → imp_ship, imp_ship_bcompany, imp_ship_cloud, imp_ship_boom
- 订单 → imp_order, imp_order_2025, imp_order_bcompany, dt_order_detail
- 客户 → customer_bcompany, customer_cloud, customer_shop, bas_customer, wms_customer_info
- 退款 → imp_refund_bcompany, imp_refund_2023begin
- 财务发票 → finance_sales_invoice, finance_transaction_erp
- 商品/产品/SKU → dg_goods_daily_sku, dg_goods_bestselling, dg_goods_stock_weekly, imp_goods_type
- 营销费/推广费 → imp_promotion_money, imp_promotion_money_bcompany
- 库存 → snap_wms_stock, sync_wms_stock, mid_wms_goods_stock, imp_stock
- 物流/快递/运费 → postage_calc_detail, postage_deliver_fee, wms_deliver_info
- 员工/人员 → oa_staff_info, com_userlist, imp_staff_info
- 考勤/打卡 → oa_attend_daily, oa_punch_record
- 预算 → imp_budget_*
- 备货 → imp_stock
- 代理商/经销商 → customer_bcompany (cust_level 区分级别)
- WMS台账 → cus_ledger_header_history, cus_ledger_month_summary

重要字段说明：
- customer_bcompany.area = 业务团队名（满天星、BOSS、明星等），不是地理区域
- customer_bcompany.zone = 地理大区（华东、华南、华中、华北、西南）
- customer_bcompany.province = 省份
- customer_bcompany.city = 城市
- imp_ship_bcompany.cust_code 关联 customer_bcompany.cust_code
- imp_ship_bcompany 没有 area/zone/province 字段，需要 JOIN customer_bcompany 获取

FineBI 看板常用查询模式（来自 dms_board_sql）：
- 分公司回款: dms_cwallet.dcw_custom_wallet_flow + dms_cwallet.dcw_custom_wallet_flow_related
- 订单统计: dms_trading.dt_order + dms_trading.dt_order_detail
- 发货数据: dms_trading.dt_deliver + dms_trading.dt_deliver_detail
- 售后数据: dms_trading.dt_after_sale + dms_trading.dt_after_sale_detail
- 客户信息: dms_distributor.dd_cust_customer + dms_distributor.dd_cust_contract_subject_rel
- 商品信息: dms_goods.goods + dms_goods.goods_sku
- 钱包余额: dms_cwallet.dcw_custom_wallet_flow (flow_type: in/out)
- 区域划分: dms_distributor.view_dd_cust_customer_info.region
"""

# Few-shot 示例：常见问题 → SQL 模式
FEW_SHOT = """
示例1：
问题：上个月回款总额多少
SQL：SELECT SUM(money) AS total FROM imp_money WHERE DATE_FORMAT(audit_time, '%Y-%m') = DATE_FORMAT(DATE_SUB(CURDATE(), INTERVAL 1 MONTH), '%Y-%m')

示例2：
问题：哪个产品卖得最好？前5名
SQL：SELECT goods_name, SUM(num) AS total_qty FROM imp_ship GROUP BY goods_name ORDER BY total_qty DESC LIMIT 5

示例3：
问题：本月每天的出货金额趋势
SQL：SELECT DATE(deliver_time) AS dt, SUM(amount) AS daily_amount FROM imp_ship_bcompany WHERE DATE_FORMAT(deliver_time, '%Y-%m') = DATE_FORMAT(CURDATE(), '%Y-%m') GROUP BY dt ORDER BY dt

示例4：
问题：华东区上季度销售额（需要 JOIN 客户表获取区域，zone 字段才是地理大区）
SQL：SELECT SUM(s.amount) AS total FROM imp_ship_bcompany s JOIN customer_bcompany c ON s.cust_code = c.cust_code WHERE c.zone = '华东' AND s.deliver_time BETWEEN DATE_FORMAT(DATE_SUB(CURDATE(), INTERVAL 1 QUARTER), '%Y-%m-01') AND LAST_DAY(DATE_SUB(CURDATE(), INTERVAL 1 MONTH))

示例5：
问题：各区域销售额排名（zone 是地理大区）
SQL：SELECT c.zone, SUM(s.amount) AS total FROM imp_ship_bcompany s JOIN customer_bcompany c ON s.cust_code = c.cust_code GROUP BY c.zone ORDER BY total DESC

示例6（来自FineBI看板）：
问题：分公司回款排名
SQL：SELECT amount, custom_subject_code, custom_name FROM (SELECT SUM(CASE WHEN flow_type = 'out' THEN 0-flow_amount ELSE flow_amount END) AS amount, custom_subject_code, custom_name FROM dms_cwallet.dcw_custom_wallet_flow a LEFT JOIN dms_cwallet.dcw_custom_wallet_flow_related b ON a.flow_no = b.flow_no WHERE a.sale_mode = 'bcompany' AND b.custom_bcompany_type = 'branch_office' AND b.custom_wallet = 'ACC_CASH_BAL' AND a.create_time BETWEEN #{startTime} AND #{endTime} GROUP BY custom_subject_code, custom_name) t ORDER BY amount DESC

示例7（来自FineBI看板）：
问题：订单数据统计
SQL：SELECT COUNT(DISTINCT o.order_no) AS totalOrders, COUNT(DISTINCT o.customer_code) AS totalCustomers, IFNULL(SUM(CASE WHEN o.sale_mode = 'bcompany' AND od.customer_wallet_code IN ('ACC_CASH_BAL', 'ACC_SPECIAL', 'ACC_CASH_POSTAGE') THEN od.transaction_subtotal WHEN o.sale_mode = 'cloud' AND od.customer_wallet_code IN ('ACC_CASH_BAL', 'ACC_CASH_SPL', 'ACC_CASH_POSTAGE') THEN od.transaction_subtotal ELSE 0 END), 0) AS totalAmount FROM dms_trading.dt_order o INNER JOIN dms_trading.dt_order_detail od ON o.order_no = od.order_no WHERE o.del_flag = 'N' AND o.payment_status != 'UNPAID' AND o.order_status IN ('PENDING_SEND', 'SENDING', 'COMPLETED')

示例8（来自FineBI看板）：
问题：商品销售情况
SQL：SELECT IFNULL(g.sku_short_name, g.sku_name) AS goods_name, SUM(wms_deliver_count) AS saleCount, SUM(amount) AS amount FROM dms_trading.view_bcompany_order_info o LEFT JOIN dms_goods.goods_sku g ON o.goods_code = g.sku_code WHERE o.deliver_time BETWEEN #{startTime} AND #{endTime} GROUP BY goods_name ORDER BY saleCount DESC
"""


def select_tables(question: str, client) -> list[str]:
    """让 LLM 根据问题选出相关表，并验证表名有效。"""
    table_list = list_tables_text()
    valid_names = get_valid_table_names()

    prompt = f"""数据库中的所有表：

{table_list}

---

{BIZ_HINT}

---

用户问题：{question}

请选出与这个问题相关的表名，每行一个。只返回表名，不要其他内容。
注意：如果涉及区域/地区维度，需要用 customer_bcompany 表的 area 字段做 JOIN。"""

    result = client.generate(prompt).strip()

    # 解析并验证表名
    selected = []
    for line in result.split("\n"):
        name = line.strip().split("--")[0].strip().split(" ")[0].strip()
        if not name or name.startswith("#") or name.startswith("```"):
            continue
        # 精确匹配
        if name in valid_names:
            if name not in selected:
                selected.append(name)
        else:
            # 模糊匹配：LLM 可能写了部分表名
            for valid in valid_names:
                if name in valid and valid not in selected:
                    selected.append(valid)
                    break

    return selected


def generate_sql(question: str, schema: str, client, error_hint: str = "") -> str:
    """生成 SQL，可附带错误提示。"""
    extra = ""
    if error_hint:
        extra = f"\n注意：上一次生成的 SQL 执行报错：{error_hint}\n请修正后重新生成。"

    prompt = f"""你是一个 MySQL SQL 专家。根据 schema 和问题生成查询。

数据库 schema：
{schema}

---

以下是常见问题的 SQL 示例，供参考：
{FEW_SHOT}

---

用户问题：{question}

规则：
1. 只返回纯 SQL，不要解释，不要 markdown
2. 只用 SELECT，禁止 INSERT/UPDATE/DELETE/DROP
3. ORDER BY 不能用中文别名，用原始列名或聚合表达式
4. 时间过滤用 DATE_FORMAT 或 BETWEEN
5. 没写 LIMIT 的自动加 LIMIT 100{extra}"""

    sql = client.generate(prompt).strip()

    # 去掉 markdown 包裹
    if sql.startswith("```"):
        lines = sql.split("\n")
        sql = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:]).strip()

    if not sql:
        sql = "ERROR: LLM 未能生成 SQL"

    return sql


def summarize(question: str, sql: str, result: dict, client) -> str:
    """让 LLM 总结查询结果。"""
    summary_prompt = f"""用户问了一个数据分析问题，SQL 查询结果如下。

问题：{question}
SQL：{sql}
结果（共 {result['row_count']} 行）：
列：{', '.join(result['columns'])}
数据：{str(result['rows'][:20])}

请用简洁的中文总结这个查询结果，回答用户的问题。给出关键数字，必要时指出趋势或异常。"""

    return client.generate(summary_prompt)


def ask(question: str, table_filter=None, history: list = None) -> dict:
    """主流程：问题 → 选表 → SQL → 结果 → 总结。

    Args:
        question: 用户问题
        table_filter: 指定表名列表（跳过选表步骤）
        history: 多轮对话历史 [{"q": "...", "sql": "...", "summary": "..."}]
    """
    client = get_client()

    # 多轮对话：把历史拼进问题
    if history:
        context_parts = []
        for h in history[-3:]:  # 只保留最近 3 轮
            context_parts.append(f"问题：{h['q']}\nSQL：{h['sql']}")
        context = "\n---\n".join(context_parts)
        full_question = f"之前的对话：\n{context}\n\n当前问题：{question}"
    else:
        full_question = question

    # 第一步：选表
    if table_filter:
        selected = table_filter
    else:
        selected = select_tables(full_question, client)

    if not selected:
        return {
            "sql": "", "error": "无法确定相关的数据表，请换个问法",
            "result": None, "summary": None, "tables": [],
        }

    # 第二步：加载 schema
    schema = load_schema(selected)

    # 第三步：生成 SQL + 执行（带重试）
    sql = generate_sql(question, schema, client)

    try:
        result = sql_executor.execute(sql)
    except Exception as e:
        # 重试：把错误信息和 schema 都告诉 LLM
        sql2 = generate_sql(question, schema, client, error_hint=f"{str(e)}\n请仔细对照上面的 schema，确保所有列名都存在。")
        try:
            result = sql_executor.execute(sql2)
            sql = sql2
        except Exception as e2:
            return {
                "sql": sql2, "error": str(e2),
                "result": None, "summary": None, "tables": selected,
            }

    # 第四步：总结
    summary = summarize(question, sql, result, client)

    return {
        "sql": sql,
        "error": None,
        "result": result,
        "summary": summary,
        "tables": selected,
    }
