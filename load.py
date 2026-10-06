# -*- coding: utf-8 -*-
"""SE373 · Buổi 03 · Khởi tạo mô hình ngôn ngữ hỗ trợ Tool Calling.

Generation parameters (slide "Generation parameters") được đặt TẠI ĐÂY, không nằm trong prompt:
  - temperature = 0   : agent đặt vé cần output ổn định (trích ràng buộc, chọn tool, JSON đúng schema),
                        không cần sáng tạo. Chỉnh bằng LLM_TEMPERATURE (để trống = dùng mặc định của model).
  - max_tokens        : giới hạn độ dài output của MỖI lần gọi -> chặn output dài bất thường, giữ chi phí
                        dự đoán được (budget.py vẫn chặn tổng token). Chỉnh bằng LLM_MAX_TOKENS.
  - top_p             : không đặt (mặc định nhà cung cấp).

"Không phải model hoặc API nào cũng hỗ trợ cùng một tập generation parameters" (slide):
  Gemini 3.x dùng sampling cố định và BỎ QUA temperature (langchain-google-genai báo UserWarning).
  Với các model này ta KHÔNG gửi temperature, và tính ổn định dựa vào structured output (schema)
  + harness kiểm bằng code, không dựa vào sampling.

AFC (Automatic Function Calling) của Google GenAI SDK: SDK tự gọi hàm Python rồi gửi kết quả lại model.
Agent này KHÔNG dùng AFC: LangChain chỉ gửi KHAI BÁO tool (tên, mô tả, schema), model trả tool_call,
harness mới là bên kiểm và thực thi ("model đề xuất, application quyết định"). Cảnh báo/log về AFC mà
SDK in ra khi LangChain gọi Models.generate_content chỉ mang tính thông tin -> tắt cho log gọn.
"""
import logging
import os
import warnings

from dotenv import load_dotenv

load_dotenv()

logging.getLogger("google_genai").setLevel(logging.ERROR)          # log "AFC is enabled ..." / AFC không khuyến nghị
warnings.filterwarnings("ignore", message=r".*automatic function calling.*", category=UserWarning)

# Tiền tố model dùng sampling cố định (không nhận temperature / top_p)
FIXED_SAMPLING_PREFIXES = ("gemini-3",)


def supports_sampling_params(model_name: str) -> bool:
    return not model_name.lower().startswith(FIXED_SAMPLING_PREFIXES)


def generation_params(model_name: str = "") -> dict:
    """Tham số sinh cho model `model_name`. temperature bị bỏ khi model không hỗ trợ hoặc để trống."""
    params = {"max_tokens": int(os.getenv("LLM_MAX_TOKENS", "1024"))}
    temp = os.getenv("LLM_TEMPERATURE", "0").strip()
    if temp and supports_sampling_params(model_name):
        params["temperature"] = float(temp)
    return params


def get_model(supplier: str | None = None, model_name: str | None = None):
    """Khởi tạo ChatModel dựa trên biến môi trường SUPPLIER và các biến liên quan.

    Hỗ trợ:
      - google: ChatGoogleGenerativeAI (mặc định gemini-3.5-flash-lite hoặc từ .env)
      - openai: ChatOpenAI
      - anthropic: ChatAnthropic
    """
    supplier = (supplier or os.getenv("SUPPLIER", "google")).lower()

    if supplier == "google":
        from langchain_google_genai import ChatGoogleGenerativeAI
        name = model_name or os.getenv("GOOGLE_MODEL", "gemini-3.5-flash-lite")
        g = generation_params(name)
        kw = {"temperature": g["temperature"]} if "temperature" in g else {}
        return ChatGoogleGenerativeAI(model=name, google_api_key=os.getenv("GOOGLE_API_KEY"),
                                      max_output_tokens=g["max_tokens"], **kw)
    if supplier == "openai":
        from langchain_openai import ChatOpenAI
        name = model_name or os.getenv("OPENAI_MODEL", "gpt-4o-mini")
        return ChatOpenAI(model=name, api_key=os.getenv("OPENAI_API_KEY"), **generation_params(name))
    if supplier == "anthropic":
        from langchain_anthropic import ChatAnthropic
        name = model_name or os.getenv("ANTHROPIC_MODEL", "claude-3-5-haiku-latest")
        return ChatAnthropic(model=name, api_key=os.getenv("ANTHROPIC_API_KEY"), **generation_params(name))
    raise ValueError(f"Unsupported supplier: {supplier}. Chọn google, openai hoặc anthropic.")
