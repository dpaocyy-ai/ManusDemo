import os
import requests

TOOLS = [
    {
        "name": "web_search",
        "description": "使用搜索引擎查询互联网上的实时信息。当需要获取最新新闻、事实数据或未知信息时使用。",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "搜索关键词"
                }
            },
            "required": ["query"]
        }
    }
]

def execute_tool(tool_name, arguments):
    """执行工具并返回结果"""
    if tool_name == "web_search":
        query = arguments.get("query", "")
        serper_api_key = os.getenv("SERPER_API_KEY")
        
        if serper_api_key and serper_api_key != "your_serper_api_key_here":
            # 模式一: Serper API 真实 Google 搜索
            try:
                url = "https://google.serper.dev/search"
                headers = {
                    "X-API-KEY": serper_api_key,
                    "Content-Type": "application/json"
                }
                payload = {"q": query, "num": 5}
                response = requests.post(url, json=payload, headers=headers, timeout=15)
                response.raise_for_status()
                data = response.json()
                
                results = []
                for item in data.get("organic", [])[:5]:
                    title = item.get("title", "")
                    link = item.get("link", "")
                    snippet = item.get("snippet", "")
                    results.append(f"标题: {title}\n链接: {link}\n摘要: {snippet}")
                
                if results:
                    return "\n\n".join(results)
                
                # 尝试知识图谱结果
                if data.get("knowledgeGraph"):
                    kg = data["knowledgeGraph"]
                    return f"【知识图谱】\n{kg.get('title', '')}: {kg.get('description', '')}"
                
                return "未找到相关结果。"
                
            except requests.exceptions.Timeout:
                return f"搜索超时，请稍后重试。"
            except requests.exceptions.RequestException as e:
                return f"Serper 搜索出错: {str(e)}"
        
        else:
            # 模拟搜索结果 (用于演示流程)
            mock_results = f"""【模拟搜索结果 - 关键词: {query}】

1. 标题: {query} - 维基百科
   链接: https://zh.wikipedia.org/wiki/{query}
   摘要: {query}是一个重要的概念/事物，在多个领域都有广泛应用...

2. 标题: {query}最新资讯 - 新闻网
   链接: https://news.example.com/{query}
   摘要: 最新报道显示，{query}相关的发展取得了重大进展...

3. 标题: 深入了解{query} - 技术博客
   链接: https://blog.example.com/{query}-guide
   摘要: 本文将详细介绍{query}的核心概念、使用方法和最佳实践...

提示: 这是模拟数据。如需真实搜索，请在 .env 中配置 SERPER_API_KEY。"""
            
            return mock_results
            
    return "Unknown tool"
