from openai import OpenAI

client = OpenAI(
  base_url="https://api.featherless.ai/v1",
  api_key="rc_223c9c4f1f78380b1f1a6eee07530b6360f0f12a41a71136dc642d510a969cc5",
)

response = client.chat.completions.create(
  model='Qwen/Qwen3-8B',
  messages=[
    {"role": "system", "content": "You are a helpful assistant."},
    {"role": "user", "content": "Hello!"}
  ],
)
print(response.model_dump()['choices'][0]['message']['content'])
