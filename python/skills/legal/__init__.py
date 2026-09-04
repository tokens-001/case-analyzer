"""
法律技能库 —— Legal AI Skills

每个技能是独立的 Python 模块，接口统一：输入文字 → 输出结构化结果。

使用方式：
    from skills.legal import extract_dispute
    result = extract_dispute.执行(判例文字, api_key)

    from skills.legal import verify_laws
    warnings = verify_laws.verify_law_citation_realness(法条库目录, 分析1, 分析2, ...)

分类：
    AI技能（调DeepSeek）:
        extract_dispute         — 核心争议提取
        extract_reasoning       — 推理链路提取
        find_unanswered         — 未回答问题发现
        assess_transfer         — 可平移性评估
        generate_summary        — 案例总结
        find_counter_arguments  — 反例检索
        structure_judgment      — 判决结构化
        audit_argument_chain    — 论证链审查
        detect_missing_evidence — 证据缺失检测
        discover_opposing_laws  — 相反法条发现

    本地校验技能（不调API）:
        verify_laws             — 法条校验全家桶
        trace_citations         — 溯源对比
        score_analysis          — 分析质量评估
"""
