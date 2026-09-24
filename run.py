import uvicorn
import webbrowser
import os

if __name__ == "__main__":
    print("=" * 60)
    print(" VideoClip 拍打声识别与精准剪辑合并系统 正在启动...")
    print(" 访问地址: http://127.0.0.1:8000")
    print("=" * 60)

    # 尝试自动在默认浏览器中打开页面
    try:
        webbrowser.open("http://127.0.0.1:8000")
    except Exception:
        pass

    uvicorn.run("web.app:app", host="127.0.0.1", port=8000, reload=True)
