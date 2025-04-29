import json
import re
import urllib.request
import urllib.error
import os
import nest_asyncio
from pyngrok import ngrok

nest_asyncio.apply()
ngrok_token = os.environ.get("NGROK_TOKEN")
if not ngrok_token: print("Ngrok認証トークンが'NGROK_TOKEN'環境変数に設定されていません。")
ngrok.set_auth_token(ngrok_token)
tunnels = ngrok.get_tunnels()

# 呼び出すFastAPIサーバーのエンドポイントURL
API_ENDPOINT = tunnels[0].public_url + "/generate"


# Lambda コンテキストからリージョンを抽出する関数
def extract_region_from_arn(arn):
    match = re.search('arn:aws:lambda:([^:]+):', arn)
    if match:
        return match.group(1)
    return "us-east-1"


def lambda_handler(event, context):
    try:
        print("Received event:", json.dumps(event))

        # Cognitoで認証されたユーザー情報を取得
        user_info = None
        if 'requestContext' in event and 'authorizer' in event['requestContext']:
            user_info = event['requestContext']['authorizer']['claims']
            print(f"Authenticated user: {user_info.get('email') or user_info.get('cognito:username')}")

        # リクエストボディの解析
        body = json.loads(event['body'])
        message = body['message']
        conversation_history = body.get('conversationHistory', [])

        print("Processing message:", message)

        # 会話履歴を使用
        messages = conversation_history.copy()

        # ユーザーメッセージを追加
        messages.append({
            "role": "user",
            "content": message
        })

        prompts = ""
        for msg in messages:
            if msg["role"] == "user":
                prompts += f"User: {msg['content']}\n"
            elif msg["role"] == "assistant":
                prompts += f"Assistant: {msg['content']}\n"

        if messages[-1]["role"] == "user":
            prompts += "Assistant: "
        elif messages[-1]["role"] == "assistant":
            prompts += "User: "

        # FastAPIに送信するペイロードを作成
        request_payload = {
            "prompt": prompts,
            "max_new_tokens": 512,
            "do_sample": True,
            "temperature": 0.7,
            "top_p": 0.9
        }

        # リクエストデータをエンコード
        data = json.dumps(request_payload).encode('utf-8')

        # HTTPリクエスト作成
        req = urllib.request.Request(
            API_ENDPOINT,
            data=data,
            headers={'Content-Type': 'application/json'},
            method='POST'
        )

        print(f"Sending request to FastAPI endpoint: {API_ENDPOINT}")

        # リクエスト送信とレスポンス受信
        with urllib.request.urlopen(req) as response:
            response_body = response.read()
            fastapi_response = json.loads(response_body)

        print("FastAPI response:", json.dumps(fastapi_response, default=str))

        # FastAPIの応答検証
        if not fastapi_response.get('generated_text'):
            raise Exception("No response content from FastAPI")

        assistant_response = fastapi_response['generated_text']

        # アシスタント応答を会話履歴に追加
        messages.append({
            "role": "assistant",
            "content": assistant_response
        })

        # 成功レスポンスの返却
        return {
            "statusCode": 200,
            "headers": {
                "Content-Type": "application/json",
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Headers": "Content-Type,X-Amz-Date,Authorization,X-Api-Key,X-Amz-Security-Token",
                "Access-Control-Allow-Methods": "OPTIONS,POST"
            },
            "body": json.dumps({
                "success": True,
                "response": assistant_response,
                "conversationHistory": messages
            })
        }

    except urllib.error.HTTPError as e:
        error_message = e.read().decode()
        print("HTTPError:", error_message)
        status_code = e.code
    except urllib.error.URLError as e:
        error_message = str(e.reason)
        print("URLError:", error_message)
        status_code = 500
    except Exception as e:
        error_message = str(e)
        print("Error:", error_message)
        status_code = 500

    # 失敗レスポンスの返却
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Headers": "Content-Type,X-Amz-Date,Authorization,X-Api-Key,X-Amz-Security-Token",
            "Access-Control-Allow-Methods": "OPTIONS,POST"
        },
        "body": json.dumps({
            "success": False,
            "error": error_message
        })
    }
