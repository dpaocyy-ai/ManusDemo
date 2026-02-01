import os
import json
import asyncio
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from openai import OpenAI
from dotenv import load_dotenv
from tools import TOOLS, execute_tool
from prompts import PLANNER_PROMPT, EXECUTOR_PROMPT, SUMMARY_PROMPT, VERIFY_PROMPT

# 加载环境变量
load_dotenv()

app = FastAPI()

# 配置 CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 初始化 DeepSeek 客户端
api_key = os.getenv("DEEPSEEK_API_KEY")
client = None
if api_key:
    client = OpenAI(
        api_key=api_key,
        base_url="https://api.deepseek.com"
    )
else:
    print("警告: 未找到 DEEPSEEK_API_KEY 环境变量，请在 .env 文件中配置。")

class Message(BaseModel):
    content: str

def clean_json_string(s):
    """清理 markdown 标记，提取 JSON 字符串"""
    s = s.strip()
    if s.startswith("```json"):
        s = s[7:]
    if s.startswith("```"):
        s = s[3:]
    if s.endswith("```"):
        s = s[:-3]
    return s.strip()

async def process_chat(message_content: str):
    """生成器函数，用于流式返回处理进度"""
    
    if not client:
        yield json.dumps({"type": "error", "content": "API Key not configured"}) + "\n"
        return

    try:
        # ==================== 1. Planner 阶段 ====================
        yield json.dumps({"type": "status", "content": "正在规划任务..."}) + "\n"
        
        tool_descriptions = json.dumps(TOOLS, ensure_ascii=False, indent=2)
        system_prompt = PLANNER_PROMPT.format(tool_list=tool_descriptions)
        
        response = client.chat.completions.create(
            model="deepseek-reasoner", # 使用 reasoner 进行规划
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": message_content}
            ]
        )
        
        planner_content = response.choices[0].message.content
        
        # 尝试解析 JSON 计划
        try:
            cleaned_plan = clean_json_string(planner_content)
            plan = json.loads(cleaned_plan)
            # 验证 plan 格式
            if not isinstance(plan, list):
                raise ValueError("Plan must be a list")
        except Exception as e:
            # 如果解析失败，回退到直接返回内容
            yield json.dumps({"type": "message", "content": planner_content}) + "\n"
            return

        # 发送计划给前端
        yield json.dumps({"type": "plan", "content": plan}) + "\n"
        
        # ==================== 2. Executor 阶段 ====================
        final_results = []
        
        for task in plan:
            task_id = task.get("id")
            task_desc = task.get("task")
            
            # 更新前端：开始执行某个任务
            yield json.dumps({"type": "task_start", "id": task_id}) + "\n"
            
            executor_prompt = EXECUTOR_PROMPT.format(
                task=task_desc,
                tool_list=tool_descriptions
            )
            
            # 调用 Executor (可以使用 deepseek-chat 或 reasoner，这里用 chat 响应更快且更易遵循 JSON)
            # 注意：DeepSeek API 目前统一用 deepseek-reasoner 或 deepseek-chat
            # 为了保证 JSON 格式稳定性，这里尝试用 deepseek-chat (V3)，如果只有 reasoner 可用则继续用 reasoner
            executor_response = client.chat.completions.create(
                model="deepseek-chat", 
                messages=[
                    {"role": "system", "content": executor_prompt},
                    {"role": "user", "content": "开始执行"}
                ]
            )
            
            exec_content = executor_response.choices[0].message.content
            # print(f"Executor Output for Task {task_id}: {exec_content}") # 注释掉 Executor 的原始输出
            
            try:
                action_data = json.loads(clean_json_string(exec_content))
                
                if action_data.get("action") == "tool_call":
                    tool_name = action_data.get("tool_name")
                    args = action_data.get("arguments")
                    
                    yield json.dumps({"type": "log", "content": f"调用工具: {tool_name} 参数: {args}"}) + "\n"
                    
                    # 执行工具
                    tool_result = execute_tool(tool_name, args)
                    final_results.append(f"任务 {task_id} 结果: {tool_result}")
                    
                elif action_data.get("action") == "reply":
                    final_results.append(f"任务 {task_id} 结果: {action_data.get('content')}")
                
            except Exception as e:
                final_results.append(f"任务 {task_id} 执行出错: {str(e)}")
            
            # 更新前端：任务完成
            yield json.dumps({"type": "task_done", "id": task_id}) + "\n"
            
            # 模拟一点延迟，让用户看清过程
            await asyncio.sleep(0.5)

        # ==================== 3. 最终汇总 ====================
        summary_input = f"用户问题：{message_content}\n\n执行结果：{json.dumps(final_results, ensure_ascii=False)}"
        print("\n" + "=" * 60)
        print("【汇总模型输入 - 含 Executor 执行结果】")
        print("=" * 60)
        print(summary_input)
        print("=" * 60 + "\n")
        
        summary_response = client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {"role": "system", "content": SUMMARY_PROMPT},
                {"role": "user", "content": summary_input}
            ]
        )
        final_answer = summary_response.choices[0].message.content
        
        # ==================== 4. Verify 智能体验证与优化 ====================
        verify_response = client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {"role": "system", "content": VERIFY_PROMPT},
                {"role": "user", "content": f"用户问题：{message_content}\n\n待校验的回答：\n{final_answer}"}
            ]
        )
        verified_answer = verify_response.choices[0].message.content
        
        print("\n" + "=" * 60)
        print("【Verify 输出】")
        print("=" * 60)
        print(verified_answer)
        print("=" * 60 + "\n")
        
        yield json.dumps({"type": "message", "content": verified_answer}) + "\n"

    except Exception as e:
        print(f"Process Error: {e}")
        yield json.dumps({"type": "error", "content": str(e)}) + "\n"

@app.post("/chat")
async def chat(message: Message):
    return StreamingResponse(
        process_chat(message.content),
        media_type="application/x-ndjson"
    )

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
