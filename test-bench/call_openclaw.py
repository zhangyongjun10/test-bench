#!/usr/bin/env python3
import requests
import json

# 配置信息
API_URL = 'http://192.168.12.179:18789/v1/chat/completions'
API_KEY = '5250a5b07883838d8b6f3357f81b681d3040eb535795f228'
MODEL = 'openclaw:main'
USER_SESSION = 'openclaw-test-session-123'

def call_openclaw(content: str) -> dict:
    """调用openclaw接口"""
    headers = {
        'Authorization': f'Bearer {API_KEY}',
        'Content-Type': 'application/json'
    }

    data = {
        "model": MODEL,
        "messages": [{"role": "user", "content": content}],
        "user": USER_SESSION
    }

    response = requests.post(API_URL, headers=headers, json=data)
    response.raise_for_status()
    return response.json()

def main():
    print("OpenClaw API 调用工具")
    print("-" * 30)

    while True:
        # 获取用户输入
        content = input("\n请输入要发送的内容 (输入 'quit' 退出): ")

        if content.lower() in ['quit', 'exit', 'q']:
            print("退出程序")
            break

        if not content.strip():
            continue

        try:
            print("\n正在请求...")
            result = call_openclaw(content)
            print("\n返回结果:")
            print(json.dumps(result, indent=2, ensure_ascii=False))
        except Exception as e:
            print(f"\n请求出错: {str(e)}")

if __name__ == "__main__":
    main()
