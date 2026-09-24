import os
import uuid
import asyncio
import json
from typing import Dict, Any, List, Optional
from fastapi import FastAPI, UploadFile, File, Form, HTTPException, BackgroundTasks
from fastapi.responses import HTMLResponse, FileResponse, StreamingResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from core.pipeline import VideoPipeline
from core.audio_extractor import SUPPORTED_EXTENSIONS

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STORAGE_DIR = os.path.join(BASE_DIR, "storage")

app = FastAPI(title="Video Impact Clip Manager", version="1.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

pipeline = VideoPipeline(STORAGE_DIR)

# 挂载静态资源
app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "web", "static")), name="static")

# 内存中维护任务进度
TASKS_STATUS: Dict[str, Dict[str, Any]] = {}

class RenderRequest(BaseModel):
    video_filename: str
    intervals: List[List[float]]
    original_name: Optional[str] = None

@app.get("/", response_class=HTMLResponse)
async def index():
    html_path = os.path.join(BASE_DIR, "web", "templates", "index.html")
    with open(html_path, "r", encoding="utf-8") as f:
        return f.read()

@app.post("/api/upload")
async def upload_video(file: UploadFile = File(...)):
    """上传原始视频文件（兼容现代格式与老旧格式 rmvb, rm, wmv, mpg, vob, avi, flv 等）"""
    if not file.filename:
        raise HTTPException(status_code=400, detail="文件名为空")

    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in SUPPORTED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的文件扩展名 {ext}。已支持主流格式(mp4, mov, mkv, webm)及经典传统格式(mpg, mpeg, wmv, rm, rmvb, avi, vob, flv, ts 等)"
        )

    # 生成安全文件名
    safe_filename = f"{uuid.uuid4().hex[:10]}_{file.filename}"
    save_path = os.path.join(pipeline.upload_dir, safe_filename)

    with open(save_path, "wb") as buffer:
        while chunk := await file.read(1024 * 1024 * 5): # 5MB chunk
            buffer.write(chunk)

    try:
        # 获取基础信息并准备 H5 预览能力（若为 rmvb/wmv 等古老格式会自动生成快速 web 预览流）
        prep_res = pipeline.prepare_video_playback(safe_filename)
        video_info = prep_res["video_info"]
        playback_url = prep_res["playback_url"]
    except Exception as e:
        if os.path.exists(save_path):
            os.remove(save_path)
        raise HTTPException(status_code=400, detail=f"无法解析该视频文件: {str(e)}")

    return {
        "status": "success",
        "filename": safe_filename,
        "original_name": file.filename,
        "video_info": video_info,
        "is_converted": prep_res["is_converted"],
        "preview_filename": prep_res.get("preview_filename"),
        "url": playback_url
    }

@app.post("/api/analyze")
async def analyze_video(
    background_tasks: BackgroundTasks,
    video_filename: str = Form(...),
    sensitivity: float = Form(0.15),
    pre_seconds: float = Form(1.2),
    post_seconds: float = Form(1.2),
    min_interval: float = Form(1.5)
):
    """发起拍打声识别异步分析"""
    task_id = f"analyze_{uuid.uuid4().hex[:8]}"
    TASKS_STATUS[task_id] = {
        "status": "running",
        "progress": 0.0,
        "message": "任务初始化中...",
        "result": None
    }

    def run_detection():
        try:
            def on_progress(p, msg):
                TASKS_STATUS[task_id]["progress"] = p
                TASKS_STATUS[task_id]["message"] = msg

            res = pipeline.process_detection(
                video_filename=video_filename,
                sensitivity=sensitivity,
                pre_seconds=pre_seconds,
                post_seconds=post_seconds,
                min_interval_sec=min_interval,
                progress_cb=on_progress
            )
            TASKS_STATUS[task_id]["status"] = "success"
            TASKS_STATUS[task_id]["progress"] = 1.0
            TASKS_STATUS[task_id]["result"] = res
            TASKS_STATUS[task_id]["message"] = "分析完成！"
        except Exception as e:
            TASKS_STATUS[task_id]["status"] = "failed"
            TASKS_STATUS[task_id]["message"] = f"分析出错: {str(e)}"

    background_tasks.add_task(run_detection)

    return {"task_id": task_id, "status": "started"}

@app.post("/api/render")
async def render_video(
    background_tasks: BackgroundTasks,
    req: RenderRequest
):
    """根据确定后的区间列表截取并合并视频"""
    task_id = f"render_{uuid.uuid4().hex[:8]}"
    TASKS_STATUS[task_id] = {
        "status": "running",
        "progress": 0.0,
        "message": "正在准备剪辑任务...",
        "result": None
    }

    intervals_tuple = [(float(s), float(e)) for s, e in req.intervals]

    def run_render():
        try:
            def on_progress(p, msg):
                TASKS_STATUS[task_id]["progress"] = p
                TASKS_STATUS[task_id]["message"] = msg

            res = pipeline.process_render(
                video_filename=req.video_filename,
                intervals=intervals_tuple,
                original_name=req.original_name,
                progress_cb=on_progress
            )
            TASKS_STATUS[task_id]["status"] = "success"
            TASKS_STATUS[task_id]["progress"] = 1.0
            TASKS_STATUS[task_id]["result"] = res
            TASKS_STATUS[task_id]["message"] = "合并导出成功！"
        except Exception as e:
            TASKS_STATUS[task_id]["status"] = "failed"
            TASKS_STATUS[task_id]["message"] = f"剪辑合并出错: {str(e)}"

    background_tasks.add_task(run_render)

    return {"task_id": task_id, "status": "started"}

@app.get("/api/task/{task_id}")
async def get_task_status(task_id: str):
    """查询任务进度与结果状态"""
    info = TASKS_STATUS.get(task_id)
    if not info:
        raise HTTPException(status_code=404, detail="未找到该任务")
    return info

@app.post("/api/open-folder")
async def open_output_folder():
    """在 Windows 资源管理器中打开导出目录"""
    export_dir = pipeline.export_dir
    if not os.path.exists(export_dir):
        os.makedirs(export_dir, exist_ok=True)
    try:
        os.startfile(export_dir)
        return {"status": "success", "path": export_dir}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"打开文件夹失败: {str(e)}")

@app.post("/api/clear-storage")
async def clear_temp_storage():
    """一键清理 uploads 和 audio 临时存储目录中的所有文件"""
    deleted_count = 0
    freed_bytes = 0

    for folder in [pipeline.upload_dir, pipeline.audio_dir]:
        if not os.path.exists(folder):
            continue
        for item in os.listdir(folder):
            item_path = os.path.join(folder, item)
            try:
                if os.path.isfile(item_path):
                    size = os.path.getsize(item_path)
                    os.remove(item_path)
                    deleted_count += 1
                    freed_bytes += size
                elif os.path.isdir(item_path):
                    import shutil
                    shutil.rmtree(item_path, ignore_errors=True)
                    deleted_count += 1
            except Exception:
                pass

    freed_mb = round(freed_bytes / (1024 * 1024), 1)
    return {
        "status": "success",
        "deleted_count": deleted_count,
        "freed_mb": freed_mb,
        "message": f"成功清理 {deleted_count} 个临时文件，释放约 {freed_mb} MB 磁盘空间！"
    }

@app.get("/api/preview-status/{filename}")
async def check_preview_status(filename: str):
    """检查后台轻量预览流文件是否已转码完成"""
    preview_path = os.path.join(pipeline.upload_dir, filename)
    if os.path.exists(preview_path) and os.path.getsize(preview_path) > 1024:
        return {"ready": True, "url": f"/api/media/uploads/{filename}"}
    return {"ready": False}

@app.post("/api/select-local")
async def select_local_file(path: Optional[str] = Form(None)):
    """
    解法一核心实现：
    若前端未传 path，通过系统原生文件对话框弹窗让用户在电脑中点选；
    若传入了 path，直接就地校验并解析元数据，实现 0.05 秒瞬时零拷贝导入！
    """
    selected_path = path

    if not selected_path:
        # 在子线程中唤起 Windows 系统的原生文件选择窗口
        def pick_file():
            import tkinter as tk
            from tkinter import filedialog
            root = tk.Tk()
            root.withdraw()
            root.attributes('-topmost', True)
            types = [
                ("常见视频文件", "*.mp4 *.mov *.mkv *.wmv *.rmvb *.rm *.avi *.flv *.webm *.mpg *.mpeg *.ts *.vob"),
                ("所有文件", "*.*")
            ]
            file_path = filedialog.askopenfilename(
                title="选择要进行拍打声识别的视频文件",
                filetypes=types
            )
            root.destroy()
            return file_path

        import asyncio
        loop = asyncio.get_event_loop()
        selected_path = await loop.run_in_executor(None, pick_file)

    if not selected_path:
        return {"status": "cancelled", "message": "用户取消了文件选择"}

    selected_path = os.path.normpath(selected_path)
    if not os.path.exists(selected_path):
        raise HTTPException(status_code=400, detail="指定的视频文件不存在")

    ext = os.path.splitext(selected_path)[1].lower()
    if ext not in SUPPORTED_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"不支持的视频格式: {ext}")

    try:
        prep_res = pipeline.prepare_video_playback(selected_path)
        video_info = prep_res["video_info"]
        playback_url = prep_res["playback_url"]
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"无法解析该视频文件: {str(e)}")

    original_name = os.path.basename(selected_path)

    return {
        "status": "success",
        "filename": selected_path, # 直接使用本地绝对路径，零网络传输、零磁盘拷贝！
        "original_name": original_name,
        "video_info": video_info,
        "is_converted": prep_res["is_converted"],
        "preview_filename": prep_res.get("preview_filename"),
        "url": playback_url
    }

@app.get("/api/media/direct")
async def get_direct_media(path: str):
    """直接流式读取本机任意目录的视频文件，支持 H5 Range 拖动 Seek"""
    import urllib.parse
    real_path = urllib.parse.unquote(path)
    if not os.path.exists(real_path):
        raise HTTPException(status_code=404, detail="视频文件不存在")

    ext = os.path.splitext(real_path)[1].lower()
    media_types = {
        ".mp4": "video/mp4",
        ".webm": "video/webm",
        ".wav": "audio/wav",
        ".mp3": "audio/mpeg"
    }
    media_type = media_types.get(ext, "application/octet-stream")
    return FileResponse(real_path, media_type=media_type, filename=os.path.basename(real_path))

@app.get("/api/media/{folder}/{filename}")
async def get_media_file(folder: str, filename: str):
    """支持 H5 Range 视频流传输播放"""
    if folder not in ["uploads", "audio", "outputs"]:
        raise HTTPException(status_code=403, detail="非法访问路径")

    file_path = os.path.join(STORAGE_DIR, folder, filename)
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="媒体文件不存在")

    ext = os.path.splitext(filename)[1].lower()
    media_types = {
        ".mp4": "video/mp4",
        ".webm": "video/webm",
        ".wav": "audio/wav",
        ".mp3": "audio/mpeg"
    }
    media_type = media_types.get(ext, "application/octet-stream")

    return FileResponse(file_path, media_type=media_type, filename=filename)
