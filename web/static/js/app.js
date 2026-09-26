// 核心前端业务控制器
window.addEventListener("DOMContentLoaded", () => {
    // 状态管理
    const state = {
        uploadedFile: null,       // 上传返回信息
        events: [],               // 识别到的拍打事件点
        intervals: [],            // 最终剪辑合并区间
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
            valInterval.innerText = `${Number(e.target.value).toFixed(2)} 秒`;
        });
    }
    if (paramPre && valPre) {
        paramPre.addEventListener("input", (e) => {
            valPre.innerText = `${Number(e.target.value).toFixed(1)} 秒`;
            if (state.uploadedFile && state.events.length > 0) {
                recalcIntervals();
                renderEventsList();
            }
        });
    }
    if (paramPost && valPost) {
        paramPost.addEventListener("input", (e) => {
            valPost.innerText = `${Number(e.target.value).toFixed(1)} 秒`;
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
        // 每个识别点增加 locked 属性 (默认未加锁 false)
        state.events = (result.events || []).map(ev => ({
            ...ev,
            locked: false
        }));
        state.intervals = result.intervals || [];

        // 渲染事件列表
        renderEventsList();

        // 识别完成后展示区间批量舍弃面板
        if (batchTrimPanel) batchTrimPanel.classList.remove("hidden");

        if (btnAnalyze) btnAnalyze.disabled = false;
        if (btnRenderVideo) btnRenderVideo.disabled = (state.intervals.length === 0);
        hideProgress();
    }

    // 渲染识别出的拍打列表与截取区间 (支持锁定与极简展示)
    function renderEventsList() {
        if (!eventsList) return;

        if (badgeCount) badgeCount.innerText = `${state.events.length} 个拍打点`;
        if (statMergedCount) statMergedCount.innerText = state.intervals.length;
        const totalDuration = state.intervals.reduce((acc, curr) => acc + (curr[1] - curr[0]), 0);
        if (statTotalDuration) statTotalDuration.innerText = `${totalDuration.toFixed(1)}s`;

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
            const card = document.createElement("div");

            // 卡片样式：若锁定，呈现稳重的琥珀暗金边框与锁定背景
            card.className = isLocked
                ? "cursor-pointer select-none flex flex-col justify-between p-3 rounded-xl bg-amber-950/25 border border-amber-500/40 hover:border-amber-400/80 transition-all duration-150 group shadow-md"
                : "cursor-pointer select-none flex flex-col justify-between p-3 rounded-xl bg-slate-950/70 border border-slate-800 hover:border-rose-500/70 hover:bg-slate-800/80 transition-all duration-150 group shadow-md";

            // 点击卡片任意一处均跳转播放
            card.onclick = () => jumpToTime(ev.time);

            // 锁按钮的图标状态
            const lockIcon = isLocked
                ? `<svg class="w-3.5 h-3.5 text-amber-400" fill="currentColor" viewBox="0 0 20 20"><path fill-rule="evenodd" d="M5 9V7a5 5 0 0110 0v2a2 2 0 012 2v5a2 2 0 01-2 2H5a2 2 0 01-2-2v-5a2 2 0 012-2zm8-2v2H7V7a3 3 0 016 0z" clip-rule="evenodd"/></svg>`
                : `<svg class="w-3.5 h-3.5 text-slate-500 group-hover:text-slate-400" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 11V7a4 4 0 118 0m-4 8v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2z"/></svg>`;

            // “负面”按钮：将该片段标记为负面样本(非拍打噪音)并删除
            const negativeBtn = isLocked
                ? `<span class="p-1 text-slate-600 cursor-not-allowed opacity-30" title="该片段已锁定，不可操作">
                     <svg class="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 12H9m12 0a9 9 0 11-18 0 9 9 0 0118 0z" /></svg>
                   </span>`
                : `<button class="p-1 text-slate-500 hover:text-orange-400 hover:bg-slate-700/50 rounded-lg transition" title="标记为负面样本(非拍打噪音)并删除，供AI模型学习" onclick="event.stopPropagation(); markNegative(${idx});">
                     <svg class="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 12H9m12 0a9 9 0 11-18 0 9 9 0 0118 0z" /></svg>
                   </button>`;

            // “删除”按钮：仅删除片段，不加入负面样本
            const deleteBtn = isLocked
                ? `<span class="p-1 text-slate-600 cursor-not-allowed opacity-30" title="该片段已锁定，不可删除">
                     <svg class="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/></svg>
                   </span>`
                : `<button class="p-1 text-slate-500 hover:text-rose-400 hover:bg-slate-700/50 rounded-lg transition" title="仅删除片段(不加入负面样本)" onclick="event.stopPropagation(); removeEvent(${idx});">
                     <svg class="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/></svg>
                   </button>`;

            card.innerHTML = `
                <!-- 顶部序列与控制按钮 -->
                <div class="flex items-center justify-between mb-2">
                    <span class="w-6 h-6 rounded-lg ${isLocked ? 'bg-amber-500/20 text-amber-300 border-amber-500/30' : 'bg-rose-500/20 text-rose-400 border-rose-500/30 group-hover:bg-rose-500 group-hover:text-white'} text-xs flex items-center justify-center font-bold border transition">
                        #${idx + 1}
                    </span>
                    <div class="flex items-center gap-0.5">
                        <!-- 锁按钮 -->
                        <button class="p-1 hover:bg-slate-800/80 rounded-lg transition" title="${isLocked ? '已加锁保护(点击解锁)' : '锁定该片段(不可删除/舍弃)'}" onclick="event.stopPropagation(); toggleLock(${idx});">
                            ${lockIcon}
                        </button>
                        <!-- 负面按钮 (加入负面样本并删除) -->
                        ${negativeBtn}
                        <!-- 删除按钮 (仅删除不加入负样本) -->
                        ${deleteBtn}
                    </div>
                </div>

                <!-- 拍打发生时间码与置信度 -->
                <div class="flex items-baseline justify-between mt-1">
                    <span class="text-base font-mono font-bold ${isLocked ? 'text-amber-200' : 'text-slate-100 group-hover:text-rose-300'} transition">
                        ${formatTime(ev.time)}
                    </span>
                    <div class="flex items-center gap-1">
                        ${ev.ai_score !== undefined && ev.ai_score !== null ? `<span class="text-[9px] font-mono px-1 py-0.2 rounded bg-purple-500/20 text-purple-300 border border-purple-500/30" title="Google YAMNet AI 判定为拍打/抽打的预测概率: ${(ev.ai_score * 100).toFixed(0)}%">AI ${(ev.ai_score * 100).toFixed(0)}%</span>` : ''}
                        <span class="text-[10px] font-medium px-1.5 py-0.5 rounded ${isLocked ? 'bg-amber-500/10 text-amber-300 border-amber-500/30' : 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20'}">
                            ${(ev.confidence * 100).toFixed(0)}%
                        </span>
                    </div>
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

    // 切换锁定状态 (锁定视为用户确认的正样本 1)
    window.toggleLock = function(index) {
        if (!state.events[index]) return;
        state.events[index].locked = !state.events[index].locked;
        renderEventsList();

        // 当用户主动加锁时，自动采集为【正样本】
        if (state.events[index].locked && state.events[index].embedding) {
            submitFeedback([{
                embedding: state.events[index].embedding,
                label: 1
            }]);
        }
    };

    // 全局跳跃时间函数 (暴露给行内 onclick)
    window.jumpToTime = function(sec) {
        if (!playerOriginal) return;
        playerOriginal.currentTime = Math.max(0, sec - 0.5);
        playerOriginal.play();
    };

    // 仅删除单项：纯粹移除片段，不作为负面样本记录
    window.removeEvent = function(index) {
        if (!state.events[index]) return;
        if (state.events[index].locked) {
            alert("该片段已被锁定保护，无法删除！如需删除请先点击锁图标解锁。");
            return;
        }

        // 仅从列表中移除片段，不提交任何负样本反馈
        state.events.splice(index, 1);
        recalcIntervals();
        renderEventsList();
    };

    // 标记为负面样本并删除：明确属于噪音误报，提交给AI模型学习排除
    window.markNegative = function(index) {
        if (!state.events[index]) return;
        if (state.events[index].locked) {
            alert("该片段已被锁定保护，无法操作！如需标记负面请先点击锁图标解锁。");
            return;
        }

        const removed = state.events[index];
        // 明确将该片段作为【负样本】采集学习
        if (removed && removed.embedding) {
            submitFeedback([{
                embedding: removed.embedding,
                label: 0
            }]);
        }

        state.events.splice(index, 1);
        recalcIntervals();
        renderEventsList();
    };

    // 批量舍弃：舍弃当前时间点之前的所有未锁定片段 (仅裁剪丢弃，不加入负面样本)
    if (btnDiscardBefore) {
        btnDiscardBefore.addEventListener("click", () => {
            if (!playerOriginal || state.events.length === 0) return;
            const curTime = playerOriginal.currentTime;
            const toRemove = state.events.filter(ev => ev.time < curTime && !ev.locked);

            if (toRemove.length === 0) {
                alert(`在当前时间点 ${formatTime(curTime)} 之前没有可舍弃的未锁定片段。`);
                return;
            }

            const confirmed = confirm(`确定要舍弃 ${formatTime(curTime)} 之前的所有未锁定片段吗？\n共将移除 ${toRemove.length} 个片段（仅删除，不计入负面样本库）。已锁定的片段将保留。`);
            if (!confirmed) return;

            state.events = state.events.filter(ev => ev.time >= curTime || ev.locked);
            recalcIntervals();
            renderEventsList();
        });
    }

    // 批量舍弃：舍弃当前时间点之后的所有未锁定片段 (仅裁剪丢弃，不加入负面样本)
    if (btnDiscardAfter) {
        btnDiscardAfter.addEventListener("click", () => {
            if (!playerOriginal || state.events.length === 0) return;
            const curTime = playerOriginal.currentTime;
            const toRemove = state.events.filter(ev => ev.time > curTime && !ev.locked);

            if (toRemove.length === 0) {
                alert(`在当前时间点 ${formatTime(curTime)} 之后没有可舍弃的未锁定片段。`);
                return;
            }

            const confirmed = confirm(`确定要舍弃 ${formatTime(curTime)} 之后的所有未锁定片段吗？\n共将移除 ${toRemove.length} 个片段（仅删除，不计入负面样本库）。已锁定的片段将保留。`);
            if (!confirmed) return;

            state.events = state.events.filter(ev => ev.time <= curTime || ev.locked);
            recalcIntervals();
            renderEventsList();
        });
    }

    // 重新计算并融合区间
    function recalcIntervals() {
        if (!state.uploadedFile || !state.uploadedFile.video_info) return;

        const pre = parseFloat(paramPre.value) || 1.0;
        const post = parseFloat(paramPost.value) || 1.0;
        const videoDur = state.uploadedFile.video_info.duration;

        const raw = state.events.map(ev => [
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

    // 点击“合并并保存” (自动将最终保留的片段作为【正样本】学习巩固)
    if (btnRenderVideo) {
        btnRenderVideo.addEventListener("click", async () => {
            if (!state.uploadedFile || state.intervals.length === 0) return;

            // 自动把用户最终认可并合成的所有片段作为【正样本】收集
            const posItems = state.events.filter(it => it.embedding).map(it => ({
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
                        original_name: state.uploadedFile.original_name
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

    // 渲染完成
    function onRenderComplete(result) {
        hideProgress();
        if (btnRenderVideo) btnRenderVideo.disabled = false;

        // 提示已自动保存到 D:\videocliout，并显示快速打开文件夹按钮
        if (result && result.export_saved) {
            if (saveLocationTag) {
                saveLocationTag.innerText = `成片已成功合并并存入: D:\\videocliout\\${result.output_filename}`;
                saveLocationTag.classList.remove("hidden");
            }
            if (btnOpenDir) {
                btnOpenDir.classList.remove("hidden");
                btnOpenDir.onclick = async () => {
                    try {
                        await fetch("/api/open-folder", { method: "POST" });
                    } catch (e) {
                        alert("无法自动呼出文件夹，请直接在资源管理器中打开 D:\\videocliout");
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
