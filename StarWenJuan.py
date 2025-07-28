import logging
import random
import re
import threading
import traceback
from threading import Thread
import time
from typing import List
import json
import os

from playwright.sync_api import sync_playwright, Page, Browser
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
import openai

# 配置logging
logging.basicConfig(
    level=logging.INFO,
    format="【%(asctime)s】%(levelname)s - %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


def scan_config_files():
    """扫描config目录中的json配置文件"""
    config_dir = "config"
    if not os.path.exists(config_dir):
        logger.error(f"配置目录 {config_dir} 不存在！")
        logger.error("请确保config目录存在并包含配置文件。")
        exit(1)

    config_files = []
    for file in os.listdir(config_dir):
        if file.endswith(".json"):
            config_path = os.path.join(config_dir, file)
            try:
                with open(config_path, "r", encoding="utf-8") as f:
                    config = json.load(f)
                    if "openai" in config and "model" in config["openai"]:
                        model_name = config["openai"]["model"]
                        config_files.append(
                            {"path": config_path, "model": model_name, "config": config}
                        )
            except Exception as e:
                logger.error(f"读取配置文件 {file} 失败: {e}")
                continue

    return config_files


def load_config():
    """加载配置文件"""
    config_files = scan_config_files()

    if not config_files:
        logger.error("未找到有效的配置文件！")
        logger.error("请确保config目录中存在包含openai.model字段的json配置文件。")
        exit(1)

    if len(config_files) == 1:
        logger.info(f"找到配置文件: {os.path.basename(config_files[0]['path'])}")
        logger.info(f"模型: {config_files[0]['model']}")
        return config_files[0]["config"]

    logger.info("找到以下配置文件:")
    for i, config_file in enumerate(config_files, 1):
        logger.info(
            f"{i}. {os.path.basename(config_file['path'])} - 模型: {config_file['model']}"
        )

    while True:
        try:
            choice = int(input(f"\n请选择配置文件 (1-{len(config_files)}): "))
            if 1 <= choice <= len(config_files):
                selected_config = config_files[choice - 1]
                logger.info(
                    f"已选择: {os.path.basename(selected_config['path'])} - {selected_config['model']}"
                )
                return selected_config["config"]
            else:
                logger.warning(f"请输入1到{len(config_files)}之间的数字！")
        except ValueError:
            logger.warning("请输入一个有效的数字！")


# 加载配置
config = load_config()
openai_config = config["openai"]
generation_params = config["generation_params"]
submission_params = config["submission_params"]

logger.info("StarWenJuan自动填写工具")
logger.info("每次填写前会生成不同的人设，然后基于人设来回答问题")
logger.info(f"使用模型: {openai_config['model']}")
logger.info(f"API地址: {openai_config['base_url']}")

# OpenAI客户端
client = openai.OpenAI(
    base_url=openai_config["base_url"], api_key=openai_config["api_key"]
)
current_persona = None


def clean_response(response_text):
    """清理AI回复中的<think>标签，只保留实际内容"""
    if response_text.strip().startswith("<think>") and "</think>" not in response_text:
        logger.warning("AI只输出了思考过程，没有实际答案")
        return ""

    cleaned = re.sub(r"<think>.*?</think>", "", response_text, flags=re.DOTALL)
    cleaned = re.sub(r"<think>.*", "", cleaned, flags=re.DOTALL)
    cleaned = re.sub(r"</think>", "", cleaned)
    cleaned = re.sub(r"\n\s*\n", "\n", cleaned.strip())

    return cleaned.strip()


def generate_persona():
    """生成一个随机的人设"""
    max_retries = generation_params["max_retries"]
    for attempt in range(max_retries):
        try:
            logger.info(f"正在生成人设... (尝试 {attempt + 1}/{max_retries})")
            response = client.chat.completions.create(
                model=openai_config["model"],
                messages=[
                    {
                        "role": "system",
                        "content": "你是一个人设生成器。请生成一个详细的虚拟人物角色，包括年龄、性别、职业、教育背景、兴趣爱好、性格特点、生活状态等。用中文回答，保持简洁但具体。（生成的人物人设不要太过夸张，普通大学生即可）直接给出人设描述，不要使用<think>标签。",
                    },
                    {"role": "user", "content": "请生成一个完整的人物人设"},
                ],
                temperature=generation_params["persona_temperature"],
                timeout=openai_config["timeout"],
            )

            persona = response.choices[0].message.content.strip()
            persona = clean_response(persona)

            if len(persona) < 20:
                logger.warning(f"人设生成可能不完整，重试... (长度: {len(persona)})")
                continue

            logger.info(f"当前人设: {persona}")
            return persona

        except Exception as e:
            logger.error(f"生成人设失败 (尝试 {attempt + 1}/{max_retries}): {e}")
            if attempt == max_retries - 1:
                logger.warning("人设生成多次失败，使用默认人设")
                return "一个普通的大学生，性格开朗，喜欢学习和运动"
            time.sleep(generation_params["retry_delay"])


def ask_ai_for_answer(question_text, options, question_type, persona):
    """向AI询问如何回答问题"""
    max_retries = generation_params["max_retries"]
    for attempt in range(max_retries):
        try:
            if question_type == "single":
                prompt = f"根据以下人设回答单选题。人设：{persona}\n\n问题：{question_text}\n选项：{options}\n请直接返回选项编号(如：1)，不要解释。"
            elif question_type == "multiple":
                prompt = f"根据以下人设回答多选题。人设：{persona}\n\n问题：{question_text}\n选项：{options}\n请返回所选选项编号，用逗号分隔(如：1,3,5)，不要解释。"
            elif question_type == "text":
                prompt = f"根据以下人设回答填空题。人设：{persona}\n\n问题：{question_text}\n请提供一个简短、真实的答案，不要解释。字数不超过100字，不要使用emoji表情"
            elif question_type == "scale":
                prompt = f"根据以下人设回答量表题。人设：{persona}\n\n问题：{question_text}\n选项：{options}\n请直接返回选项编号(如：3)，不要解释。"
            elif question_type == "matrix":
                prompt = f"根据以下人设回答矩阵题的一行。人设：{persona}\n\n问题：{question_text}\n选项：{options}\n请直接返回选项编号(如：2)，不要解释。"
            elif question_type == "dropdown":
                prompt = f"根据以下人设回答下拉框题。人设：{persona}\n\n问题：{question_text}\n选项：{options}\n请直接返回选项编号(如：2)，不要解释。"
            elif question_type == "numeric_matrix":
                prompt = f"根据以下人设回答数字矩阵题。人设：{persona}\n\n问题：{question_text}\n选项：{options}\n请为每个选项分配一个0-10的数字（不可以是小数，要保证这几个数字加起来等于10），表示比例或程度，用逗号分隔，不要解释。"
            else:
                return "1"

            response = client.chat.completions.create(
                model=openai_config["model"],
                messages=[
                    {
                        "role": "system",
                        "content": "你是一个问卷填写助手，根据给定人设来回答问题。回答要简洁准确，符合人设特点。直接给出答案，不要使用<think>标签进行思考。",
                    },
                    {"role": "user", "content": prompt},
                ],
                temperature=generation_params["answer_temperature"],
                timeout=openai_config["timeout"],
            )

            answer = response.choices[0].message.content.strip()
            answer = clean_response(answer)

            if not answer or len(answer.strip()) == 0:
                logger.warning(
                    f"AI回答为空，重试... (尝试 {attempt + 1}/{max_retries})"
                )
                continue

            if question_type in ["single", "scale", "matrix", "dropdown"]:
                if not re.search(r"\d", answer):
                    logger.warning(
                        f"选择题答案格式错误，重试... (答案: {answer[:50]}...)"
                    )
                    continue

            return answer

        except Exception as e:
            logger.error(f"AI回答失败 (尝试 {attempt + 1}/{max_retries}): {e}")
            if attempt < max_retries - 1:
                time.sleep(generation_params["retry_delay"])

    logger.warning("AI回答多次失败，使用默认答案")
    if question_type == "multiple":
        return "1"
    elif question_type == "text":
        return "无"
    else:
        return "1"


def detect(page: Page) -> List[int]:
    q_list: List[int] = []
    page_num = len(page.query_selector_all('//*[@id="divQuestion"]/fieldset'))
    for i in range(1, page_num + 1):
        questions = page.query_selector_all(f'//*[@id="fieldset{i}"]/div')
        valid_count = sum(
            1
            for question in questions
            if question.get_attribute("topic")
            and question.get_attribute("topic").isdigit()
        )
        q_list.append(valid_count)
    return q_list


def get_question_text(page: Page, current):
    """获取题目文本"""
    try:
        question_elem = page.query_selector(f"#div{current} .topichtml")
        if question_elem:
            return question_elem.text_content().strip()
        return f"第{current}题"
    except:
        return f"第{current}题"


def get_options_text(page: Page, xpath):
    """获取选项文本"""
    try:
        options = page.query_selector_all(xpath)
        option_texts = []
        for i, option in enumerate(options, 1):
            text = option.text_content().strip()
            option_texts.append(f"{i}. {text}")
        return " | ".join(option_texts)
    except:
        return "选项获取失败"


def vacant(page: Page, current, persona):
    question_text = get_question_text(page, current)
    answer = ask_ai_for_answer(question_text, "", "text", persona)
    page.fill(f"#q{current}", answer)


def single(page: Page, current, persona):
    question_text = get_question_text(page, current)
    xpath = f'//*[@id="div{current}"]/div[2]/div'
    options_text = get_options_text(page, xpath)

    a = page.query_selector_all(xpath)
    answer = ask_ai_for_answer(question_text, options_text, "single", persona)

    try:
        choice = int(answer)
        if 1 <= choice <= len(a):
            page.click(f"#div{current} > div.ui-controlgroup > div:nth-child({choice})")
        else:
            page.click(f"#div{current} > div.ui-controlgroup > div:nth-child(1)")
    except:
        page.click(f"#div{current} > div.ui-controlgroup > div:nth-child(1)")


def droplist(page: Page, current, persona):
    question_text = get_question_text(page, current)

    page.click(f"#select2-q{current}-container")
    time.sleep(0.5)

    options = page.query_selector_all(f"//*[@id='select2-q{current}-results']/li")
    options_text = get_options_text(page, f"//*[@id='select2-q{current}-results']/li")

    answer = ask_ai_for_answer(question_text, options_text, "dropdown", persona)

    try:
        choice = int(answer)
        if 1 <= choice <= len(options):
            page.click(f"//*[@id='select2-q{current}-results']/li[{choice}]")
        else:
            page.click(f"//*[@id='select2-q{current}-results']/li[1]")
    except:
        page.click(f"//*[@id='select2-q{current}-results']/li[1]")


def multiple(page: Page, current, persona):
    question_text = get_question_text(page, current)
    xpath = f'//*[@id="div{current}"]/div[2]/div'
    options_text = get_options_text(page, xpath)

    options = page.query_selector_all(xpath)
    answer = ask_ai_for_answer(question_text, options_text, "multiple", persona)

    try:
        choices = [int(x.strip()) for x in answer.split(",")]
        for choice in choices:
            if 1 <= choice <= len(options):
                css = f"#div{current} > div.ui-controlgroup > div:nth-child({choice})"
                page.click(css)
    except:
        page.click(f"#div{current} > div.ui-controlgroup > div:nth-child(1)")


def matrix(page: Page, current, persona):
    question_text = get_question_text(page, current)
    xpath1 = f'//*[@id="divRefTab{current}"]/tbody/tr'
    a = page.query_selector_all(xpath1)
    q_num = 0
    for tr in a:
        if tr.get_attribute("rowindex") is not None:
            q_num += 1

    xpath2 = f'//*[@id="drv{current}_1"]/td'
    b = page.query_selector_all(xpath2)
    options_text = get_options_text(page, xpath2)

    for i in range(1, q_num + 1):
        try:
            row_text = (
                page.query_selector(f"#drv{current}_{i} td:first-child")
                .text_content()
                .strip()
            )
            sub_question = f"{question_text} - {row_text}"
        except:
            sub_question = f"{question_text} - 第{i}小题"

        answer = ask_ai_for_answer(sub_question, options_text, "matrix", persona)

        try:
            choice = int(answer)
            if 2 <= choice <= len(b):
                page.click(f"#drv{current}_{i} > td:nth-child({choice})")
            else:
                page.click(f"#drv{current}_{i} > td:nth-child(2)")
        except:
            page.click(f"#drv{current}_{i} > td:nth-child(2)")


def reorder(page: Page, current):
    xpath = f'//*[@id="div{current}"]/ul/li'
    a = page.query_selector_all(xpath)
    for j in range(1, len(a) + 1):
        b = random.randint(j, len(a))
        page.click(f"#div{current} > ul > li:nth-child({b})")
        time.sleep(0.4)


def scale(page: Page, current, persona):
    question_text = get_question_text(page, current)
    xpath = f'//*[@id="div{current}"]/div[2]/div/ul/li'
    options_text = get_options_text(page, xpath)

    a = page.query_selector_all(xpath)
    answer = ask_ai_for_answer(question_text, options_text, "scale", persona)

    try:
        choice = int(answer)
        if 1 <= choice <= len(a):
            page.click(
                f"#div{current} > div.scale-div > div > ul > li:nth-child({choice})"
            )
        else:
            page.click(f"#div{current} > div.scale-div > div > ul > li:nth-child(1)")
    except:
        page.click(f"#div{current} > div.scale-div > div > ul > li:nth-child(1)")


def numeric_matrix(page: Page, current, persona):
    """处理数字输入矩阵题（type=10），如支出比例等"""
    question_text = get_question_text(page, current)

    input_elements = page.query_selector_all(f"#div{current} input[type='tel']")

    if not input_elements:
        logger.warning(f"第{current}题：未找到数字输入框")
        return

    try:
        column_headers = page.query_selector_all(
            f"#div{current} .ui-table-column-title"
        )
        column_info = [header.text_content().strip() for header in column_headers]
        options_text = " | ".join(f"{i+1}. {col}" for i, col in enumerate(column_info))
    except:
        options_text = f"需要填入{len(input_elements)}个数字（0-10范围内）"

    full_question = f"{question_text}\n列选项: {options_text}\n请为每列分配一个0-10的数字，用逗号分隔"
    answer = ask_ai_for_answer(full_question, options_text, "numeric_matrix", persona)

    try:
        numbers = [
            float(x.strip())
            for x in answer.split(",")
            if x.strip().replace(".", "").isdigit()
        ]

        numbers = [max(0, min(10, num)) for num in numbers]

        while len(numbers) < len(input_elements):
            numbers.append(random.randint(1, 8))

        numbers = numbers[: len(input_elements)]

        for i, input_elem in enumerate(input_elements):
            input_id = input_elem.get_attribute("id")
            if input_id:
                value = (
                    int(numbers[i])
                    if numbers[i] == int(numbers[i])
                    else round(numbers[i], 1)
                )
                page.fill(f"#{input_id}", str(value))

    except Exception as e:
        logger.error(f"第{current}题数字输入解析失败: {e}")
        for input_elem in input_elements:
            input_id = input_elem.get_attribute("id")
            if input_id:
                random_value = random.randint(1, 8)
                page.fill(f"#{input_id}", str(random_value))


def brush(page: Page):
    persona = generate_persona()

    q_list = detect(page)
    current = 0

    for j in q_list:
        for k in range(1, j + 1):
            current += 1
            q_type = page.get_attribute(f"#div{current}", "type")

            if q_type == "1" or q_type == "2":
                vacant(page, current, persona)
            elif q_type == "3":
                single(page, current, persona)
            elif q_type == "4":
                multiple(page, current, persona)
            elif q_type == "5":
                scale(page, current, persona)
            elif q_type == "6":
                matrix(page, current, persona)
            elif q_type == "7":
                droplist(page, current, persona)
            elif q_type == "8":
                score = random.randint(1, 100)
                page.fill(f"#q{current}", str(score))
            elif q_type == "10":
                numeric_matrix(page, current, persona)
            elif q_type == "11":
                reorder(page, current)
            else:
                logger.warning(f"第{k}题为不支持题型！题型代码：{q_type}")

            time.sleep(0.5)

        time.sleep(0.5)
        try:
            page.click("#divNext")
            time.sleep(0.5)
        except:
            page.click('//*[@id="ctlNext"]')
    submit(page)


def submit(page: Page):
    time.sleep(submission_params["submit_button_delay"])

    try:
        page.click('//*[@id="layui-layer1"]/div[3]/a')
        time.sleep(submission_params["submit_button_delay"])
    except:
        pass

    try:
        page.click('//*[@id="SM_BTN_1"]')
        time.sleep(submission_params["verification_delay"])
    except:
        pass

    try:
        slider = page.query_selector('//*[@id="nc_1__scale_text"]/span')
        sliderButton = page.query_selector('//*[@id="nc_1_n1z"]')
        if slider and sliderButton:
            slider_text = slider.text_content()
            if slider_text and str(slider_text).startswith("请按住滑块"):
                bbox = slider.bounding_box()
                if bbox:
                    width = bbox["width"]
                    page.drag_and_drop(
                        '//*[@id="nc_1_n1z"]',
                        '//*[@id="nc_1__scale_text"]/span',
                        source_position={"x": 0, "y": 0},
                        target_position={"x": width, "y": 0},
                    )
    except:
        pass


def wait_for_completion(
    page: Page, original_url: str, max_wait_time: int = None
) -> bool:
    """超快速检测问卷提交完成"""
    if max_wait_time is None:
        max_wait_time = submission_params["completion_wait_timeout"]

    start_time = time.time()
    check_interval = 0.03

    try:
        current_url = page.url
        if current_url != original_url:
            logger.info(f"页面已跳转: {current_url}")
            return True
    except:
        pass

    while time.time() - start_time < max_wait_time:
        try:
            current_url = page.url

            if current_url != original_url:
                logger.info(f"检测到页面跳转: {current_url}")
                return True

            url_lower = current_url.lower()
            if any(
                keyword in url_lower
                for keyword in [
                    "complete",
                    "完成",
                    "finish",
                    "success",
                    "thank",
                    "end",
                    "result",
                ]
            ):
                logger.info(f"检测到完成页面: {current_url}")
                return True

            try:
                success_indicators = page.query_selector_all(
                    "[class*='success'], [class*='complete'], [class*='finish'], [id*='success'], [id*='complete'], [id*='finish']"
                )
                if success_indicators:
                    logger.info("检测到完成提示元素")
                    return True
            except:
                pass

            try:
                has_completion_text = page.evaluate(
                    """
                    () => {
                        const text = document.body.innerText.toLowerCase();
                        const keywords = ['提交成功', '感谢您的参与', '问卷已提交', 'thank you', 'complete', 'success'];
                        return keywords.some(keyword => text.includes(keyword));
                    }
                """
                )
                if has_completion_text:
                    logger.info("检测到完成文本内容")
                    return True
            except:
                pass

            try:
                title = page.title().lower()
                if any(
                    keyword in title
                    for keyword in [
                        "完成",
                        "成功",
                        "感谢",
                        "complete",
                        "success",
                        "thank",
                    ]
                ):
                    logger.info(f"检测到完成页面标题: {page.title()}")
                    return True
            except:
                pass

            time.sleep(check_interval)

        except Exception as e:
            time.sleep(0.01)
            continue

    try:
        final_url = page.url
        if final_url != original_url:
            logger.info(f"超时后检测到URL变化: {final_url}")
            return True
    except:
        pass

    logger.warning(f"等待完成超时 ({max_wait_time}秒)")
    return False


def run(xx, yy):
    global cur_num, cur_fail

    with sync_playwright() as p:
        launch_options = {
            "headless": False,
            "args": [
                "--disable-blink-features=AutomationControlled",
                "--disable-web-security",
                "--disable-features=VizDisplayCompositor",
            ],
        }

        browser = p.chromium.launch(**launch_options)

        while cur_num < target_num:
            context = browser.new_context(
                viewport={"width": 550, "height": 650},
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            )

            page = context.new_page()

            page.add_init_script(
                """
                Object.defineProperty(navigator, 'webdriver', {
                    get: () => undefined,
                });
            """
            )

            try:
                page.goto(url)
                original_url = page.url
                brush(page)

                if wait_for_completion(page, original_url):
                    cur_num += 1
                    final_url = page.url
                    logger.info(
                        f"已填写{cur_num}份 - 失败{cur_fail}次 - {time.strftime('%H:%M:%S', time.localtime(time.time()))} "
                    )
                    logger.info(f"完成页面: {final_url}")
                else:
                    logger.warning("提交可能失败或超时")

                context.close()
            except Exception as e:
                traceback.print_exc()
                lock.acquire()
                cur_fail += 1
                lock.release()
                logger.error(
                    f"已失败{cur_fail}次,失败超过{int(fail_threshold)}次将强制停止"
                )
                if cur_fail >= fail_threshold:
                    logger.critical("失败次数过多，程序将强制停止")
                    context.close()
                    browser.close()
                    quit()
                context.close()
                continue

        browser.close()


if __name__ == "__main__":
    logger.info("=== StarWenJuan自动填写工具 ===")
    logger.info(f"使用模型: {openai_config['model']}")
    logger.info(f"API地址: {openai_config['base_url']}")
    logger.info("请按照提示输入相关信息：")

    try:
        logger.info("正在测试API连接...")
        test_response = client.chat.completions.create(
            model=openai_config["model"],
            messages=[{"role": "user", "content": "测试连接"}],
            max_tokens=openai_config["max_tokens_test"],
        )
        logger.info("API连接测试成功！")
    except Exception as e:
        logger.error(f"API连接失败: {e}")
        logger.error("请确保：")
        logger.error(f"1. API服务已启动并运行在 {openai_config['base_url']}")
        logger.error(f"2. 模型 {openai_config['model']} 可用")
        logger.error("3. API密钥配置正确（如果需要）")
        exit()

    while True:
        url = input("请输入问卷链接: ").strip()
        if url:
            if not url.startswith(("http://", "https://")):
                url = "https://" + url
            break
        else:
            logger.warning("问卷链接不能为空，请重新输入！")

    while True:
        try:
            target_num = int(input("请输入目标填写份数: "))
            if target_num > 0:
                break
            else:
                logger.warning("目标份数必须大于0，请重新输入！")
        except ValueError:
            logger.warning("请输入一个有效的数字！")

    while True:
        try:
            num_threads = int(
                input("请输入浏览器窗口数量 (建议1-3个，避免API频率限制): ")
            )
            if 1 <= num_threads <= 5:
                break
            else:
                logger.warning("窗口数量建议在1-5之间，请重新输入！")
        except ValueError:
            logger.warning("请输入一个有效的数字！")

    logger.info(f"配置信息:")
    logger.info(f"问卷链接: {url}")
    logger.info(f"目标份数: {target_num}")
    logger.info(f"窗口数量: {num_threads}")
    logger.info("开始运行程序...")
    logger.info("每次填写都会生成不同的人设...")

    fail_threshold = target_num / 4 + 1
    cur_num = 0
    cur_fail = 0
    lock = threading.Lock()
    threads: list[Thread] = []

    for i in range(num_threads):
        x = 50 + i * 60
        y = 50
        thread = Thread(target=run, args=(x, y))
        threads.append(thread)
        thread.start()

    for thread in threads:
        thread.join()

    logger.info("程序执行完成！")
