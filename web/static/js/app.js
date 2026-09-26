// 核心前端业务控制器
window.addEventListener("DOMContentLoaded", () => {
    // 状态管理
    const state = {
        uploadedFile: null,       // 上传返回信息
        events: [],               // 识别到的拍打事件点
        intervals: [],            // 最终剪辑合并区间
        activeEventIndex: null,   // 当前正在播放/点击的片段索引 (变绿高亮)
        currentTaskId: null,
        pollingTimer: null
    };

    // DOM 元素引用
    const dropArea = document.getElementById("drop-area");
    const videoInput = document.getElementById("video-input");
    const btnBrowseLocal = document.getElementById("btn-browse-local");
    const videoFileInfo = document.getElementById("video-file-info");
    const infoFilename = document.getElementById("info-filename");
    const infoDuration = document.getElementById("info-duration");
    const infoCodec = document.getElementById("info-codec");
    const infoConvertedTip = document.getElementById("info-converted-tip");

    const paramSensitivity = document.getElementById("param-sensitivity");
    const valSensitivity = document.getElementById("val-sensitivity");
    const paramInterval = document.getElementById("param-interval");
    const valInterval = document.getElementById("val-interval");
    const paramPre = document.getElementById("param-pre");
    const valPre = document.getElementById("val-pre");
    const paramPost = document.getElementById("param-post");
    const valPost = document.getElementById("val-post");
    const paramAi = document.getElementById("param-ai");
    const labelAi = document.getElementById("label-ai");

    const btnAnalyze = document.getElementById("btn-analyze");
    const btnTuneModel = document.getElementById("btn-tune-model");
    const selectTunerRatio = document.getElementById("select-tuner-ratio");
    const badgeTunerSamples = document.getElementById("badge-tuner-samples");
    const btnClearStorage = document.getElementById("btn-clear-storage");
    const btnRenderVideo = document.getElementById("btn-render-video");
    const progressBox = document.getElementById("progress-box");
    const progressLabel = document.getElementById("progress-label");
    const progressPercent = document.getElementById("progress-percent");
    const progressBar = document.getElementById("progress-bar");

    const playerOriginal = document.getElementById("player-original");
    const playerContainer = document.getElementById("player-container");
    const transcodingOverlay = document.getElementById("transcoding-overlay");
    const transcodePercent = document.getElementById("transcode-percent");
    const transcodeProgressBar = document.getElementById("transcode-progress-bar");
    const transcodeMsg = document.getElementById("transcode-msg");
    const playbackStatusBadge = document.getElementById("playback-status-badge");
    const infoConvertedText = document.getElementById("info-converted-text");
    const playerTip = document.getElementById("player-tip");
    const btnReupload = document.getElementById("btn-reupload");
    const originalTimeTag = document.getElementById("original-time-tag");
    const btnOpenDir = document.getElementById("btn-open-dir");
    const saveLocationTag = document.getElementById("save-location-tag");

    const btnMergeSuccess = document.getElementById("btn-merge-success");
    const mergeSuccessText = document.getElementById("merge-success-text");
    const btnChangeExportDir = document.getElementById("btn-change-export-dir");
    const labelExportDir = document.getElementById("label-export-dir");
    let currentCustomExportDir = "D:\\videocliout"; // 默认保存目录

    const batchTrimPanel = document.getElementById("batch-trim-panel");
    const trimCurTime = document.getElementById("trim-cur-time");
    const btnDiscardBefore = document.getElementById("btn-discard-before");
    const btnDiscardAfter = document.getElementById("btn-discard-after");

    const eventsList = document.getElementById("events-list");
    const badgeCount = document.getElementById("badge-count");
    const statMergedCount = document.getElementById("stat-merged-count");
    const statTotalDuration = document.getElementById("stat-total-duration");

    // 格式化时间辅助函数
    function formatTime(seconds) {
        if (isNaN(seconds)) return "00:00.0";
        const m = Math.floor(seconds / 60);
        const s = Math.floor(seconds % 60);
        const ms = Math.floor((seconds % 1) * 10);
        return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}.${ms}`;
    }

    // 参数绑定联动
    if (paramSensitivity && valSensitivity) {
        paramSensitivity.addEventListener("input", (e) => {
            valSensitivity.innerText = Number(e.target.value).toFixed(2);
        });
    }
    if (paramInterval && valInterval) {
        paramInterval.addEventListener("input", (e) => {
            valInterval.innerText = `${Number(e.target.value).toFixed(2)}s`;
        });
    }
    if (paramPre && valPre) {
        paramPre.addEventListener("input", (e) => {
            valPre.innerText = `${Number(e.target.value).toFixed(1)}s`;
            if (state.uploadedFile && state.events.length > 0) {
                recalcIntervals();
                renderEventsList();
            }
        });
    }
    if (paramPost && valPost) {
        paramPost.addEventListener("input", (e) => {
            valPost.innerText = `${Number(e.target.value).toFixed(1)}s`;
            if (state.uploadedFile && state.events.length > 0) {
                recalcIntervals();
                renderEventsList();
            }
        });
    }
    if (paramAi && labelAi) {
        paramAi.addEventListener("change", (e) => {
            labelAi.innerText = e.target.checked ? "已开启" : "已关闭";
            labelAi.className = e.target.checked ? "font-mono text-emerald-400 font-bold text-xs" : "font-mono text-slate-500 font-bold text-xs";
        });
    }

    // 上传区域绑定 (支持解法一：原生文件对话框瞬时导入 + 拖拽上传)
    if (btnBrowseLocal) {
        btnBrowseLocal.addEventListener("click", async (e) => {
            e.stopPropagation(); // 避免触发 dropArea 的 click
            await handleSelectLocalFile();
        });
    }

    if (dropArea && videoInput) {
        dropArea.addEventListener("click", () => {
            // 点击外围也可以直接唤起原生对话框
            handleSelectLocalFile();
        });

        dropArea.addEventListener("dragover", (e) => {
            e.preventDefault();
            dropArea.classList.add("border-rose-500");
        });
        dropArea.addEventListener("dragleave", () => {
            dropArea.classList.remove("border-rose-500");
        });
        dropArea.addEventListener("drop", (e) => {
            e.preventDefault();
            dropArea.classList.remove("border-rose-500");
            if (e.dataTransfer && e.dataTransfer.files.length > 0) {
                handleFileUpload(e.dataTransfer.files[0]);
            }
        });

        videoInput.addEventListener("change", (e) => {
            if (e.target.files && e.target.files.length > 0) {
                handleFileUpload(e.target.files[0]);
            }
        });
    }

    // “更换视频”按钮绑定
    if (btnReupload) {
        btnReupload.addEventListener("click", () => {
            handleSelectLocalFile();
        });
    }

    // 解法一：直接就地读取电脑本地文件，零网络传输、零拷贝，0.1秒秒开！
    async function handleSelectLocalFile(specifiedPath = null) {
        showProgress("正在快速加载本地文件...", 50);

        try {
            const formData = new FormData();
            if (specifiedPath) {
                formData.append("path", specifiedPath);
            }

            const resp = await fetch("/api/select-local", {
                method: "POST",
                body: formData
            });

            const data = await resp.json();
            if (data.status === "cancelled") {
                hideProgress();
                return;
            }

            if (!resp.ok) {
                throw new Error(data.detail || "加载本地文件失败");
            }

            applyLoadedVideo(data);
        } catch (error) {
            alert("选择本地文件出错: " + error.message);
            hideProgress();
        }
    }

    function applyLoadedVideo(data) {
        state.uploadedFile = data;

        // 显示视频信息
        if (infoFilename) infoFilename.innerText = data.original_name;
        if (infoDuration) infoDuration.innerText = `${data.video_info.duration.toFixed(1)} 秒`;
        const vCodec = (data.video_info.v_codec || "未知").toUpperCase();
        if (infoCodec) infoCodec.innerText = `${vCodec} (${data.video_info.width}×${data.video_info.height})`;

        // 根据是否为原生格式设置状态徽章与提示
        if (data.is_converted) {
            // 需要转码：先标为“后台转码预览中”
            if (playbackStatusBadge) {
                playbackStatusBadge.className = "font-mono text-amber-400 flex items-center gap-1.5 font-medium";
                playbackStatusBadge.innerHTML = `<span class="w-1.5 h-1.5 rounded-full bg-amber-400 animate-pulse"></span><span>正在转换 H5 流...</span>`;
            }
            if (infoConvertedTip) {
                infoConvertedTip.classList.remove("hidden");
                if (infoConvertedText) {
                    infoConvertedText.innerText = "非网页原生编码（如 WMV/RMVB/AVI 或特殊编码），后台正在极速转出 H5 画面";
                }
            }
            if (transcodingOverlay) {
                transcodingOverlay.classList.remove("hidden");
            }
        } else {
            // 原生支持
            if (playbackStatusBadge) {
                playbackStatusBadge.className = "font-mono text-emerald-400 flex items-center gap-1.5 font-medium";
                playbackStatusBadge.innerHTML = `<span class="w-1.5 h-1.5 rounded-full bg-emerald-400"></span><span>原生流畅播放就绪</span>`;
            }
            if (infoConvertedTip) {
                infoConvertedTip.classList.add("hidden");
            }
            if (transcodingOverlay) {
                transcodingOverlay.classList.add("hidden");
            }
        }
        if (videoFileInfo) videoFileInfo.classList.remove("hidden");

        // 上传完成后：隐藏拖拽上传框，展示原始视频播放器
        if (dropArea) dropArea.classList.add("hidden");
        if (playerContainer) playerContainer.classList.remove("hidden");
        if (originalTimeTag) originalTimeTag.classList.remove("hidden");
        if (btnReupload) btnReupload.classList.remove("hidden");
        if (playerTip) playerTip.classList.remove("hidden");

        // 载入原始播放器
        if (playerOriginal) {
            playerOriginal.src = data.url;
            playerOriginal.load();

            // 若当前格式不是浏览器原生格式，后台正在转码 preview 流，前端自动轮询就绪后无缝切换播放
            if (data.is_converted && data.preview_filename) {
                pollPreviewReady(data.preview_filename);
            }
        }

        if (btnAnalyze) btnAnalyze.disabled = false;
        hideProgress();
    }

    // 轮询预览流是否转码就绪并更新精确百分比进度
    function pollPreviewReady(previewFilename) {
        let count = 0;
        const timer = setInterval(async () => {
            count++;
            if (count > 200) { // 最多轮询 300 秒
                clearInterval(timer);
                return;
            }
            try {
                const resp = await fetch(`/api/preview-status/${encodeURIComponent(previewFilename)}`);
                const res = await resp.json();

                // 实时更新浮层和参数栏的百分比进度
                const percent = Math.round((res.progress || 0) * 100);
                if (transcodePercent) {
                    transcodePercent.innerText = `${percent}%`;
                }
                if (transcodeProgressBar) {
                    transcodeProgressBar.style.width = `${percent}%`;
                }
                if (transcodeMsg && res.message) {
                    transcodeMsg.innerText = res.message;
                }
                if (playbackStatusBadge && !res.ready) {
                    playbackStatusBadge.innerHTML = `<span class="w-1.5 h-1.5 rounded-full bg-amber-400 animate-pulse"></span><span>正在转换 H5 流 (${percent}%)...</span>`;
                }

                if (res.ready) {
                    clearInterval(timer);
                    if (playerOriginal) {
                        const cur = playerOriginal.currentTime || 0;
                        playerOriginal.src = res.url;
                        playerOriginal.load();
                        playerOriginal.currentTime = cur;
                    }
                    // 隐藏转码遮罩浮层
                    if (transcodingOverlay) {
                        transcodingOverlay.classList.add("hidden");
                    }
                    // 更新状态徽章为就绪
                    if (playbackStatusBadge) {
                        playbackStatusBadge.className = "font-mono text-emerald-400 flex items-center gap-1.5 font-medium";
                        playbackStatusBadge.innerHTML = `<span class="w-1.5 h-1.5 rounded-full bg-emerald-400"></span><span>H5 转换完成 · 流畅播放</span>`;
                    }
                    if (infoConvertedTip) {
                        if (infoConvertedText) {
                            infoConvertedText.innerText = "已自动完成 H5 兼容转换并无缝热切流，支持任意 Seek 跳转";
                        }
                    }
                }
            } catch (e) {}
        }, 1000);
    }

    // 处理传统文件上传 (复用统一的 applyLoadedVideo 渲染)
    async function handleFileUpload(file) {
        showProgress("正在载入视频文件...", 20);
        const formData = new FormData();
        formData.append("file", file);

        try {
            const resp = await fetch("/api/upload", {
                method: "POST",
                body: formData
            });
            if (!resp.ok) {
                const err = await resp.json().catch(() => ({}));
                throw new Error(err.detail || "上传失败");
            }
            const data = await resp.json();
            applyLoadedVideo(data);
        } catch (error) {
            alert("上传出错: " + error.message);
            hideProgress();
        }
    }

    // 播放器时间更新
    if (playerOriginal) {
        playerOriginal.addEventListener("timeupdate", () => {
            const curTime = playerOriginal.currentTime;
            if (originalTimeTag) {
                originalTimeTag.innerText = formatTime(curTime);
            }
            if (trimCurTime) {
                trimCurTime.innerText = formatTime(curTime);
            }
        });
    }

    // 点击“开始识别”
    if (btnAnalyze) {
        btnAnalyze.addEventListener("click", async () => {
            if (!state.uploadedFile) return;

            btnAnalyze.disabled = true;
            showProgress("已提交识别请求，正在排队分析...", 10);

            const formData = new FormData();
            formData.append("video_filename", state.uploadedFile.filename);
            formData.append("sensitivity", paramSensitivity.value);
            formData.append("min_interval", paramInterval.value);
            formData.append("pre_seconds", paramPre.value);
            formData.append("post_seconds", paramPost.value);
            formData.append("enable_ai", paramAi ? paramAi.checked : true);

            try {
                const resp = await fetch("/api/analyze", {
                    method: "POST",
                    body: formData
                });
                const data = await resp.json();
                startPolling(data.task_id, (result) => {
                    onDetectionComplete(result);
                });
            } catch (error) {
                alert("发起分析失败: " + error.message);
                btnAnalyze.disabled = false;
                hideProgress();
            }
        });
    }

    // 识别完成后的数据呈现
    function onDetectionComplete(result) {
        // 每个识别点初始化状态
        state.events = (result.events || []).map(ev => ({
            ...ev,
            locked: false,      // 是否加锁变黄 (正样本)
            is_negative: false, // 是否标记负面变红 (负样本)
            is_deleted: false   // 是否删除变灰 (废弃)
        }));
        state.activeEventIndex = null;
        recalcIntervals();

        // 渲染事件列表
        renderEventsList();

        // 识别完成后展示区间批量舍弃面板
        if (batchTrimPanel) batchTrimPanel.classList.remove("hidden");

        if (btnAnalyze) btnAnalyze.disabled = false;
        if (btnRenderVideo) btnRenderVideo.disabled = (state.intervals.length === 0);
        hideProgress();
    }

    // 渲染识别出的拍打列表与截取区间 (支持全新四色状态机：绿/黄/红/灰)
    function renderEventsList() {
        if (!eventsList) return;

        // 计算有效片段数量 (排除已删除灰色与负面红色)
        const validEvents = state.events.filter(ev => !ev.is_deleted && !ev.is_negative);
        if (badgeCount) badgeCount.innerText = `${validEvents.length} 个片段`;

        if (state.events.length === 0) {
            eventsList.innerHTML = `
                <div class="col-span-full text-center py-16 text-slate-500 text-xs">
                    未在当前灵敏度下识别到明显拍打声。<br>可尝试提高“识别灵敏度”重新检测。
                </div>
            `;
            return;
        }

        eventsList.innerHTML = "";
        state.events.forEach((ev, idx) => {
            const isLocked = !!ev.locked;
            const isNegative = !!ev.is_negative;
            const isDeleted = !!ev.is_deleted;
            const isActive = (state.activeEventIndex === idx);

            const card = document.createElement("div");

            // 四色状态样式判定：
            // 灰色优先(删除) > 红色优先(负面) > 黄色(锁住) > 绿色(点击播放激活)
            let statusClass = "";
            if (isDeleted) {
                statusClass = "is-deleted"; // 灰色
            } else if (isNegative) {
                statusClass = "is-negative"; // 红色
            } else if (isLocked) {
                statusClass = "is-locked"; // 黄色
            } else if (isActive) {
                statusClass = "is-active"; // 绿色
            }

            card.className = `clip-card cursor-pointer select-none flex flex-col justify-between p-2.5 rounded-xl transition-all duration-150 group ${statusClass}`;

            // 点击卡片任意一处均跳转播放并立刻变绿
            card.onclick = () => {
                jumpToTime(ev.time, idx);
            };

            // 1. 锁按钮的图标状态 (黄色)
            const lockIcon = isLocked
                ? `<svg class="w-3.5 h-3.5 text-amber-400" fill="currentColor" viewBox="0 0 20 20"><path fill-rule="evenodd" d="M5 9V7a5 5 0 0110 0v2a2 2 0 012 2v5a2 2 0 01-2 2H5a2 2 0 01-2-2v-5a2 2 0 012-2zm8-2v2H7V7a3 3 0 016 0z" clip-rule="evenodd"/></svg>`
                : `<svg class="w-3.5 h-3.5 text-slate-400 hover:text-amber-300" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 11V7a4 4 0 118 0m-4 8v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2z"/></svg>`;

            // 2. “负面”按钮状态 (红色)：点击变红并入负样本库，再次点击取消负面并移出样本库
            const negativeIcon = isNegative
                ? `<svg class="w-3.5 h-3.5 text-rose-400" fill="currentColor" viewBox="0 0 20 20"><path fill-rule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zM7 9a1 1 0 000 2h6a1 1 0 100-2H7z" clip-rule="evenodd"/></svg>`
                : `<svg class="w-3.5 h-3.5 text-slate-400 hover:text-rose-400" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 12H9m12 0a9 9 0 11-18 0 9 9 0 0118 0z" /></svg>`;

            // 3. “删除”按钮状态 (灰色)：点击变灰，再次点击恢复
            const deleteIcon = isDeleted
                ? `<svg class="w-3.5 h-3.5 text-slate-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" title="已删除(点击恢复)"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"/></svg>`
                : `<svg class="w-3.5 h-3.5 text-slate-400 hover:text-slate-200" fill="none" viewBox="0 0 24 24" stroke="currentColor" title="删除该片段(变灰)"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/></svg>`;

            // AI 置信率显示逻辑：只显示一个 AI 置信率
            const aiScoreVal = (ev.ai_score !== undefined && ev.ai_score !== null)
                ? (ev.ai_score * 100).toFixed(0)
                : (ev.confidence * 100).toFixed(0);

            // 徽章背景色彩
            let badgeBg = "bg-white/5 text-slate-300 border-white/10";
            let timeColor = "text-slate-100 group-hover:text-rose-300";
            if (isDeleted) {
                badgeBg = "bg-white/5 text-slate-500 border-white/5";
                timeColor = "text-slate-500 line-through";
            } else if (isNegative) {
                badgeBg = "bg-rose-500/20 text-rose-300 border-rose-500/35";
                timeColor = "text-rose-200";
            } else if (isLocked) {
                badgeBg = "bg-amber-500/20 text-amber-300 border-amber-500/35";
                timeColor = "text-amber-200";
            } else if (isActive) {
                badgeBg = "bg-emerald-500/20 text-emerald-300 border-emerald-500/35";
                timeColor = "text-emerald-300";
            }

            card.innerHTML = `
                <!-- 顶部序列与控制按钮 -->
                <div class="flex items-center justify-between mb-1.5">
                    <span class="w-5 h-5 rounded-md ${badgeBg} text-[10px] flex items-center justify-center font-mono font-bold border transition">
                        #${idx + 1}
                    </span>
                    <div class="flex items-center gap-0.5 opacity-80 group-hover:opacity-100 transition">
                        <!-- 锁按钮 (黄) -->
                        <button class="p-1 hover:bg-white/10 rounded-md transition" title="${isLocked ? '已加锁(点击解锁并移出正样本库)' : '锁住该片段(变黄并加入正样本库)'}" onclick="event.stopPropagation(); toggleLock(${idx});">
                            ${lockIcon}
                        </button>
                        <!-- 负面按钮 (红) -->
                        <button class="p-1 hover:bg-white/10 rounded-md transition" title="${isNegative ? '已标记为负面(点击取消并移出负样本库)' : '标记为负面样本(变红并加入负样本库)'}" onclick="event.stopPropagation(); toggleNegative(${idx});">
                            ${negativeIcon}
                        </button>
                        <!-- 删除按钮 (灰) -->
                        <button class="p-1 hover:bg-white/10 rounded-md transition" title="${isDeleted ? '已删除(点击恢复)' : '删除该片段(变灰不合成)'}" onclick="event.stopPropagation(); toggleDelete(${idx});">
                            ${deleteIcon}
                        </button>
                    </div>
                </div>

                <!-- 拍打发生时间码与唯一定位的 AI 置信率 -->
                <div class="flex items-baseline justify-between mt-0.5">
                    <span class="text-sm font-mono font-bold tracking-tight ${timeColor} transition">
                        ${formatTime(ev.time)}
                    </span>
                    <span class="text-[10px] font-mono font-semibold px-1.5 py-0.5 rounded-full ${isDeleted ? 'bg-white/5 text-slate-500 border border-white/5' : isNegative ? 'bg-rose-500/20 text-rose-300 border border-rose-500/30' : isLocked ? 'bg-amber-500/20 text-amber-300 border border-amber-500/30' : isActive ? 'bg-emerald-500/20 text-emerald-300 border border-emerald-500/30' : 'bg-purple-500/15 text-purple-300 border border-purple-500/25'}" title="AI 拍打置信率: ${aiScoreVal}%">
                        ${isDeleted ? '已丢弃' : isNegative ? '负样本' : isLocked ? '已锁定' : `AI ${aiScoreVal}%`}
                    </span>
                </div>
            `;
            eventsList.appendChild(card);
        });
    }

    // 初始拉取一次微调样本统计
    refreshTunerStats();

    async function refreshTunerStats() {
        try {
            const resp = await fetch("/api/tuner/stats");
            const data = await resp.json();
            if (badgeTunerSamples) {
                badgeTunerSamples.innerText = `${data.pos_count}+/${data.neg_count}-`;
                if (data.is_tuned) {
                    badgeTunerSamples.title = `微调模型已加载！(已积累 正样本:${data.pos_count}, 负样本:${data.neg_count})`;
                } else {
                    badgeTunerSamples.title = `尚未微调 (已积累 正样本:${data.pos_count}, 负样本:${data.neg_count}，至少各需2个样本)`;
                }
            }
        } catch (e) {}
    }

    // 发送用户反馈至后端样本库
    async function submitFeedback(items) {
        if (!items || items.length === 0) return;
        try {
            await fetch("/api/tuner/feedback", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ items: items })
            });
            refreshTunerStats();
        } catch (e) {}
    }

    // 从后端样本库移除用户反馈
    async function removeFeedback(items) {
        if (!items || items.length === 0) return;
        try {
            await fetch("/api/tuner/remove-feedback", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ items: items })
            });
            refreshTunerStats();
        } catch (e) {}
    }

    // 1. 切换锁定状态 (变黄入正样本库；取消锁变回并移出正样本库)
    window.toggleLock = function(index) {
        if (!state.events[index]) return;
        const ev = state.events[index];

        if (ev.locked) {
            // 取消锁住：移出正样本库
            ev.locked = false;
            if (ev.embedding) {
                removeFeedback([{ embedding: ev.embedding, label: 1 }]);
            }
        } else {
            // 设为锁住：变黄，并加入正样本库
            ev.locked = true;
            ev.is_deleted = false; // 加锁自动解除删除
            if (ev.is_negative) {
                // 如果之前是负面，先解除负面并移出负样本库
                ev.is_negative = false;
                if (ev.embedding) {
                    removeFeedback([{ embedding: ev.embedding, label: 0 }]);
                }
            }
            if (ev.embedding) {
                submitFeedback([{ embedding: ev.embedding, label: 1 }]);
            }
        }

        recalcIntervals();
        renderEventsList();
    };

    // 2. 切换负面状态 (变红入负样本库；取消负面变回并移出负样本库)
    window.toggleNegative = function(index) {
        if (!state.events[index]) return;
        const ev = state.events[index];

        if (ev.is_negative) {
            // 取消负面：变回并从负样本库中移除
            ev.is_negative = false;
            if (ev.embedding) {
                removeFeedback([{ embedding: ev.embedding, label: 0 }]);
            }
        } else {
            // 标记为负面：变红并加入负样本库
            ev.is_negative = true;
            ev.is_deleted = false;
            if (ev.locked) {
                // 如果之前锁住，解除锁并移出正样本库
                ev.locked = false;
                if (ev.embedding) {
                    removeFeedback([{ embedding: ev.embedding, label: 1 }]);
                }
            }
            if (ev.embedding) {
                submitFeedback([{ embedding: ev.embedding, label: 0 }]);
            }
        }

        recalcIntervals();
        renderEventsList();
    };

    // 3. 切换删除状态 (变灰；再次点击取消删除变回)
    window.toggleDelete = function(index) {
        if (!state.events[index]) return;
        const ev = state.events[index];

        if (ev.locked) {
            alert("该片段已被锁定保护，无法删除！如需删除请先点击锁图标解锁。");
            return;
        }

        // 仅切换废弃状态变灰，不加入负面样本库
        ev.is_deleted = !ev.is_deleted;
        recalcIntervals();
        renderEventsList();
    };

    // 兼容原调用的 removeEvent
    window.removeEvent = window.toggleDelete;

    // 全局跳跃时间函数 (点击卡片立刻跳转播放并变绿)
    window.jumpToTime = function(sec, idx = null) {
        if (!playerOriginal) return;
        if (idx !== null) {
            state.activeEventIndex = idx;
            renderEventsList();
        }
        playerOriginal.currentTime = Math.max(0, sec - 0.5);
        playerOriginal.play();
    };

    // 批量舍弃：将当前时间点之前的所有未锁定片段标记为已删除 (变灰)
    if (btnDiscardBefore) {
        btnDiscardBefore.addEventListener("click", () => {
            if (!playerOriginal || state.events.length === 0) return;
            const curTime = playerOriginal.currentTime;
            const toDiscard = state.events.filter(ev => ev.time < curTime && !ev.locked && !ev.is_deleted);

            if (toDiscard.length === 0) {
                alert(`在当前时间点 ${formatTime(curTime)} 之前没有可舍弃的未锁定片段。`);
                return;
            }

            const confirmed = confirm(`确定要舍弃 ${formatTime(curTime)} 之前的片段吗？\n共将把 ${toDiscard.length} 个片段标记为已丢弃(变灰，不参与合并)。已锁定的片段将保留。`);
            if (!confirmed) return;

            toDiscard.forEach(ev => { ev.is_deleted = true; });
            recalcIntervals();
            renderEventsList();
        });
    }

    // 批量舍弃：将当前时间点之后的所有未锁定片段标记为已删除 (变灰)
    if (btnDiscardAfter) {
        btnDiscardAfter.addEventListener("click", () => {
            if (!playerOriginal || state.events.length === 0) return;
            const curTime = playerOriginal.currentTime;
            const toDiscard = state.events.filter(ev => ev.time > curTime && !ev.locked && !ev.is_deleted);

            if (toDiscard.length === 0) {
                alert(`在当前时间点 ${formatTime(curTime)} 之后没有可舍弃的未锁定片段。`);
                return;
            }

            const confirmed = confirm(`确定要舍弃 ${formatTime(curTime)} 之后的片段吗？\n共将把 ${toDiscard.length} 个片段标记为已丢弃(变灰，不参与合并)。已锁定的片段将保留。`);
            if (!confirmed) return;

            toDiscard.forEach(ev => { ev.is_deleted = true; });
            recalcIntervals();
            renderEventsList();
        });
    }

    // 重新计算并融合区间 (仅有效片段：!is_deleted && !is_negative 参与生成区间和合并)
    function recalcIntervals() {
        if (!state.uploadedFile || !state.uploadedFile.video_info) return;

        const pre = parseFloat(paramPre.value) || 1.0;
        const post = parseFloat(paramPost.value) || 1.0;
        const videoDur = state.uploadedFile.video_info.duration;

        // 仅筛选有效片段
        const validEvents = state.events.filter(ev => !ev.is_deleted && !ev.is_negative);

        const raw = validEvents.map(ev => [
            Math.max(0, ev.time - pre),
            Math.min(videoDur, ev.time + post)
        ]).sort((a, b) => a[0] - b[0]);

        const merged = [];
        for (const [start, end] of raw) {
            if (merged.length === 0) {
                merged.push([start, end]);
            } else {
                const prev = merged[merged.length - 1];
                if (start <= prev[1] + 0.5) {
                    prev[1] = Math.max(prev[1], end);
                } else {
                    merged.push([start, end]);
                }
            }
        }
        state.intervals = merged;
        if (btnRenderVideo) btnRenderVideo.disabled = (state.intervals.length === 0);
    }

    // 手动选取成片保存目录
    if (btnChangeExportDir) {
        btnChangeExportDir.addEventListener("click", async () => {
            try {
                showProgress("正在选取目标文件夹...", 30);
                const resp = await fetch("/api/select-export-dir", { method: "POST" });
                const data = await resp.json();
                hideProgress();

                if (data.status === "success" && data.export_dir) {
                    currentCustomExportDir = data.export_dir;
                    if (labelExportDir) {
                        labelExportDir.innerText = currentCustomExportDir;
                        labelExportDir.title = currentCustomExportDir;
                    }
                }
            } catch (e) {
                hideProgress();
                alert("选取文件夹出错: " + e.message);
            }
        });
    }

    // 点击“合并并保存” (自动将最终保留的片段作为【正样本】学习巩固)
    if (btnRenderVideo) {
        btnRenderVideo.addEventListener("click", async () => {
            if (!state.uploadedFile || state.intervals.length === 0) return;

            // 隐藏旧的成功说明
            if (btnMergeSuccess) btnMergeSuccess.classList.add("hidden");

            // 自动把用户最终认可并合成的有效片段作为【正样本】收集
            const posItems = state.events.filter(it => !it.is_deleted && !it.is_negative && it.embedding).map(it => ({
                embedding: it.embedding,
                label: 1
            }));
            submitFeedback(posItems);

            btnRenderVideo.disabled = true;
            showProgress("正在裁剪并合并视频片段...", 5);

            try {
                const resp = await fetch("/api/render", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({
                        video_filename: state.uploadedFile.filename,
                        intervals: state.intervals,
                        original_name: state.uploadedFile.original_name,
                        export_dir: currentCustomExportDir
                    })
                });
                const data = await resp.json();
                startPolling(data.task_id, (result) => {
                    onRenderComplete(result);
                });
            } catch (error) {
                alert("发起剪辑合并失败: " + error.message);
                btnRenderVideo.disabled = false;
                hideProgress();
            }
        });
    }

    // 渲染完成：在合并按钮前面显示任务成功的说明，点击说明文字即可直接打开目录
    function onRenderComplete(result) {
        hideProgress();
        if (btnRenderVideo) btnRenderVideo.disabled = false;

        if (result && result.export_saved) {
            const finalDir = result.export_dir || currentCustomExportDir;

            // 激活“合并并保存”按钮前方的成功提示按钮
            if (btnMergeSuccess) {
                if (mergeSuccessText) {
                    mergeSuccessText.innerText = `已成功保存至 ${finalDir} (点击打开)`;
                }
                btnMergeSuccess.classList.remove("hidden");
                btnMergeSuccess.onclick = async () => {
                    try {
                        const form = new FormData();
                        form.append("folder", finalDir);
                        await fetch("/api/open-folder", { method: "POST", body: form });
                    } catch (e) {
                        alert(`无法直接唤起窗口，请在文件资源管理器中打开: ${finalDir}`);
                    }
                };
            }
        }
    }

    // 一键清理临时存储
    if (btnClearStorage) {
        btnClearStorage.addEventListener("click", async () => {
            const confirmed = confirm("确定要一键清理 uploads 与 audio 文件夹里的所有临时视频和音频文件吗？\n\n注意：此操作将清空临时上传文件，但已合并保存到 D:\\videocliout 的成片不受影响。");
            if (!confirmed) return;

            try {
                const resp = await fetch("/api/clear-storage", { method: "POST" });
                const data = await resp.json();
                alert(data.message || "临时文件已清理完毕！");

                // 重置当前工作区状态
                state.uploadedFile = null;
                state.events = [];
                state.intervals = [];

                if (dropArea) dropArea.classList.remove("hidden");
                if (playerContainer) playerContainer.classList.add("hidden");
                if (originalTimeTag) {
                    originalTimeTag.classList.add("hidden");
                    originalTimeTag.innerText = "00:00.0";
                }
                if (btnReupload) btnReupload.classList.add("hidden");
                if (playerTip) playerTip.classList.add("hidden");
                if (videoFileInfo) videoFileInfo.classList.add("hidden");
                if (playerOriginal) {
                    playerOriginal.pause();
                    playerOriginal.removeAttribute("src");
                    playerOriginal.load();
                }
                if (videoInput) videoInput.value = "";
                if (btnAnalyze) btnAnalyze.disabled = true;
                if (btnRenderVideo) btnRenderVideo.disabled = true;
                if (batchTrimPanel) batchTrimPanel.classList.add("hidden");
                if (saveLocationTag) saveLocationTag.classList.add("hidden");
                if (btnOpenDir) btnOpenDir.classList.add("hidden");
                if (btnMergeSuccess) btnMergeSuccess.classList.add("hidden");

                renderEventsList();
            } catch (err) {
                alert("清理失败: " + err.message);
            }
        });
    }

    // 点击“微调训练”按钮
    if (btnTuneModel) {
        btnTuneModel.addEventListener("click", async () => {
            btnTuneModel.disabled = true;
            try {
                const statResp = await fetch("/api/tuner/stats");
                const stats = await statResp.json();

                if (!stats.can_tune) {
                    alert(`目前收集的有效样本尚不足：\n当前已收集 正样本: ${stats.pos_count} 个, 负样本: ${stats.neg_count} 个。\n\n提示：\n- 当您点击【加锁】或最终【合并保存】时，片段会自动作为正样本记录；\n- 当您点击【红叉删除】或【批量舍弃】时，片段会自动作为负样本记录。\n正负样本各至少达到 2 个即可开启微调训练！`);
                    btnTuneModel.disabled = false;
                    return;
                }

                showProgress("正在基于人工反馈微调 YAMNet 专属分类头...", 50);

                const ratioVal = selectTunerRatio ? parseFloat(selectTunerRatio.value) : 6.0;
                const trainForm = new FormData();
                trainForm.append("ratio", ratioVal);

                const resp = await fetch("/api/tuner/train", {
                    method: "POST",
                    body: trainForm
                });
                const res = await resp.json();
                if (!resp.ok) {
                    throw new Error(res.detail || "训练失败");
                }

                hideProgress();
                alert(res.message);
                refreshTunerStats();
            } catch (err) {
                hideProgress();
                alert("微调失败: " + err.message);
            } finally {
                btnTuneModel.disabled = false;
            }
        });
    }

    // 轮询任务进度
    function startPolling(taskId, onSuccess) {
        if (state.pollingTimer) clearInterval(state.pollingTimer);

        state.pollingTimer = setInterval(async () => {
            try {
                const resp = await fetch(`/api/task/${taskId}`);
                if (!resp.ok) throw new Error("查询任务失败");
                const task = await resp.json();

                showProgress(task.message, Math.round(task.progress * 100));

                if (task.status === "success") {
                    clearInterval(state.pollingTimer);
                    onSuccess(task.result);
                } else if (task.status === "failed") {
                    clearInterval(state.pollingTimer);
                    alert(task.message);
                    hideProgress();
                }
            } catch (err) {
                clearInterval(state.pollingTimer);
                hideProgress();
            }
        }, 600);
    }

    function showProgress(label, percent) {
        if (progressBox) progressBox.classList.remove("hidden");
        if (progressLabel) progressLabel.innerText = label;
        if (progressPercent) progressPercent.innerText = `${percent}%`;
        if (progressBar) progressBar.style.width = `${percent}%`;
    }

    function hideProgress() {
        if (progressBox) progressBox.classList.add("hidden");
    }
});
