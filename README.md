# StarWenJuan自动填写系统

基于 **Playwright** 和 **OpenAI** 实现的智能问卷自动填写工具。

## 功能特性

- 🤖 **AI 智能回答**：基于 AI 生成的人设智能回答问卷问题
- 🌐 **多窗口并发**：支持多个浏览器窗口同时运行，提升填写效率
- 📊 **智能人设生成**：每次填写生成不同的人设，模拟真实用户行为
- 🔄 **自动提交**：自动处理验证码和提交流程

## 安装要求

### 1. 环境依赖

```bash
uv sync
```

### 2. 安装 Playwright

```bash
uv run playwright install chromium
```

### 3. 配置 OpenAI

在 `config/` 目录下创建配置文件，包含以下内容：

```json
{
  "openai": {
    "base_url": "你的API地址",
    "api_key": "你的API密钥",
    "model": "使用的模型名称",
    "timeout": 30,
    "max_tokens_test": 10
  },
  "generation_params": {
    "max_retries": 3,
    "retry_delay": 1,
    "persona_temperature": 0.8,
    "answer_temperature": 0.3
  },
  "submission_params": {
    "submit_button_delay": 1,
    "verification_delay": 2,
    "completion_wait_timeout": 10
  }
}
```

## 使用方法

### 1. 运行程序

```bash
uv run StarWenJuan.py
```

### 2. 输入参数

- **问卷链接**：完整的StarWenJuan链接
- **目标份数**：需要填写的问卷数量
- **窗口数量**：并发运行的浏览器窗口数（建议 1-3 个）

## 支持题型

- 单选题 (type=3)
- 多选题 (type=4)
- 填空题 (type=1,2)
- 量表题 (type=5)
- 矩阵题 (type=6)
- 下拉框 (type=7)
- 数字题 (type=8)
- 数字矩阵 (type=10)
- 排序题 (type=11)

## 注意事项

1. 确保网络连接稳定
2. 合理设置窗口数量，避免 API 频率限制
3. 遵守问卷平台的使用条款
4. 仅用于学习和研究目的

## 许可证

本项目仅供学习和研究使用，请勿用于商业用途。

## 贡献

欢迎提交 Issue 和 Pull Request 来改进项目。
