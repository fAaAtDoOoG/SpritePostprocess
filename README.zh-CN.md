# SpritePostprocess

[English](README.md) | **简体中文**

独立、离线、跨项目的动画后处理工具。它处理**已经制作好的动画**，不调用生成模型，不依赖某个角色、Unity 项目、ComfyUI 服务或历史交付目录。

提供窗口界面和命令行，共用同一套配置与处理核心。任意动作名、方向数、帧数、矩形画布都可以使用。`512 → 64/32`、八方向、16 帧和 32 PPU 都不是强制规则。

## 新手快速开始

### Windows 窗口方式（推荐）

Windows 双击 `Start.cmd`。第一次使用先点击“环境检查”，确认 Python 依赖；需要读写 Aseprite 时，还要确认 Aseprite CLI 可用。随后：

1. 选择素材目录，指定一个**尚不存在**的结果目录。
2. 选择预设并点击“创建配置”。工具会把配置放在结果目录外，避免结果目录已创建后阻塞处理。
3. 在“常用设置”中选择工作尺寸、输出尺寸、清理强度、布局与占比、预览和导出选项，然后点击“把常用设置应用到 JSON”。
4. 需要镜像、倒放、帧匹配或逐帧缩放时，再编辑“高级 JSON”。
5. 点击“保存并运行”。日志在窗口中显示；过程在后台运行，不接管 Unity。
6. 输出完成后，点击“验证结果”检查文件，或“打开结果目录”查看预览和交付文件。

界面会记住上次选择的语言；偏好保存在工具目录的 `.ui-preferences.json`。素材配置与处理报告仍使用稳定的英文 JSON 字段，因此中英文界面可以安全地打开同一份配置。

`neutral` 预设关闭白边处理、不重新调整角色占比；`pixel-character` 预设启用严格白边处理和同组固定比例放大。两者都能修改全部参数。**白色毛发、发光轮廓、雪、羽毛等素材应优先用 neutral 或 conservative，不要直接套用严格去白预设。**

界面不直接修改当前项目；修改配置不会自动运行。开始处理使用保存后的 JSON 配置。

### 命令行方式

`--lang en|zh-CN` 可以放在子命令之前或之后；也可用环境变量 `SPRITEPOST_LANG` 设置默认语言。配置字段、JSON 键名和报告结构不会随界面语言改变。

```powershell
python spritepost.py --lang zh-CN doctor

python spritepost.py init --lang zh-CN --input "E:/Art/creature/aseprite" --output "E:/Jobs/creature.json" --result-dir "E:/Delivery/creature" --preset pixel-character

python spritepost.py process "E:/Jobs/creature.json" --lang zh-CN
python spritepost.py verify "E:/Delivery/creature" --lang zh-CN
python spritepost.py inspect "E:/Art/creature/walk_front.aseprite" --lang zh-CN
```

也可以用 `Start.cmd doctor`，或 `Start.ps1 -Python "路径/python.exe" doctor`。窗口和 CLI 使用相同 Python 环境。

### 环境与迁移

需要 Python **3.10 或更高版本**。Windows 上建议建立独立环境：

```powershell
git clone https://github.com/fAaAtDoOoG/SpritePostprocess.git
cd SpritePostprocess
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\Start.cmd
```

- 运行依赖为 NumPy、OpenCV、Pillow；版本范围见 `requirements.txt`。
- GUI 使用 Python 自带 Tkinter。CLI 不要求桌面会话；Linux 可能需单独提供系统 Tk 包才能使用窗口。
- 读写 `.aseprite/.ase` 需要本机 Aseprite CLI；纯 PNG 输入并关闭 `export.aseprite` 则不需要 Aseprite。
- Aseprite 可以在界面中选择，也可通过配置 `aseprite`、环境变量 `SPRITEPOST_ASEPRITE` 或 PATH 指定；工具还会检查常见 Steam 安装位置。
- Python 可通过 `Start.ps1 -Python`、环境变量 `SPRITEPOST_PYTHON`、工具旁的 `runtime.local.json`、工具旁的 `.venv` 或 PATH 指定。

`runtime.local.json` 是工具旁可选的本机配置，必须使用绝对路径：

```json
{
  "python": "C:/Users/you/Tools/SpritePostprocess/.venv/Scripts/python.exe"
}
```

它不会提交到 Git 或放入发布包。换电脑时不要复制旧机器的绝对路径；请在新机器建立环境并选择当地 Python。

- 移到另一台机器：解压源码包，使用当地 Python 和 Aseprite。需要新环境时自行安装 `requirements.txt`；工具不偷偷下载、安装或升级依赖。
- 当前机器的本地配置复用已有 Python 环境，但核心与发布包没有 ComfyUI 路径依赖。

## 完整处理流程

```text
已有动画
  -> 读取帧和时间
  -> 可选的高分辨率帧匹配 / 帧序操作
  -> 源分辨率清理
  -> 固定工作画布和可选缩放修正
  -> 同组统一缩放和定位
  -> alpha 预乘缩小
  -> 各输出尺寸再次清理和显式镜像
  -> Aseprite / PNG / 预览 / 报告 / ZIP
  -> 文件验证
```

1. **读素材和时间轴**：支持 Aseprite、PNG 图集及逐帧 PNG。以文件实际帧数为准，不相信文件名中的 `48f`。
2. **恢复剪辑帧序（可选）**：给出高分辨率 `source` 和用户剪辑后的 `edited`，逐帧匹配；保留剪辑版的顺序与每帧时长。把原图等比归一化后比较预乘 RGBA，记录分数和次优差距。匹配低置信度时停止，输出匹配报告，不擅自选一个近似帧。可改用明确的 `frame_map`。
3. **显式帧序处理**：按需应用倒放、ping-pong；帧时长和来源记录跟着帧一起移动。
4. **源分辨率去白**：仅处理可配置的透明边缘污染、小型漂浮白点和透明区隐藏 RGB，不整幅删白。
5. **工作画布**：等比放到配置的高分辨率工作画布。小图会记录“放大不能恢复丢失细节”的警告；要保真，应提供真正的高分辨率源图。`source_at_least_work_resolution` 只说明文件像素尺寸，不证明它从未被放大过。
6. **渐进变大修正（可选）**：只有配置 `zoom` 才会执行，在工作分辨率对最终选定帧序应用连续缩放曲线，使用整个动画的固定底部中心锚点。不自动误判步态变化为镜头缩放。
7. **占比和对齐**：同一个 `group` 的所有动作共用固定缩放系数。每个动画根据整段动画的联合边界计算一次平移，不逐帧拉伸，不追着每帧边界重新定位。需要人工纠正某个方向时可明确配置 `scale_multiplier`。
8. **输出缩放**：默认 alpha 预乘 OpenCV Lanczos4。每种目标尺寸均直接由工作分辨率生成，不从 64 再缩到 32。矩形画布保持纵横比，留白不拉伸。也可选择 nearest 或 box。
9. **再次去白与镜像**：每个输出分辨率重新清理；镜像由处理好的源动画逐像素翻转，保证镜像结果一致。
10. **交付**：固定全画布 PNG 图集 + JSON manifest、Aseprite、可选逐帧 PNG、原始长度和指定帧数预览、合集预览、ZIP、完整处理报告。
11. **文件验证**：重新导出 Aseprite，逐像素对照 PNG，检查帧数、尺寸、时长、镜像关系、完整网格和 APNG 时长。只证明文件完整性，不自动替用户进行动作视觉验收。
12. **引擎边界**：Unity 可选静态检查；明确调用 `deploy` 才替换一个指定 PNG。核心不搜索游戏资源引用，不扫描修改整个项目，不改控制器或 `.anim`。

工具针对已经带透明通道的角色素材。**它不是新的背景分割模型**，不能把完全不透明的白底或棋盘格自动变成正确透明轮廓；这些输入应先完成抠图。

## 配置

所有相对路径都相对 **JSON 配置文件所在目录**。参数拼错会报错，不会静默忽略。示例：`examples/basic.json`、`examples/advanced.json`。

### 核心选项

| 字段 | 用途 |
| --- | --- |
| `name` | 交付包名称，使用安全的英文、数字、下划线、点、短横线 |
| `output` | 全新交付目录；存在则拒绝覆盖，也不得与输入目录重叠 |
| `work_size` | 工作画布 `[width,height]`，例如 `[512,512]` 或 `[768,512]` |
| `sizes` | 任意多个目标尺寸列表，支持非正方形 |
| `resample` | `lanczos4` / `nearest` / `box`；均先预乘 alpha。BOX 仿射变换因 OpenCV 限制使用线性，最终缩小使用面积滤波 |
| `cleanup.profile` | `off` / `conservative` / `strict` |
| `layout.mode` | `preserve` 保留占比位置，或 `shared_fit` 同组固定比例填充 |
| `layout.occupancy` | 同组联合边界最大目标占比，默认 `0.9` |
| `layout.anchor` | 底部中心归一化坐标，默认 `[0.5,0.95]`，不是引擎 pivot |
| `layout.allow_upscale` | 是否允许同组缩放系数大于 1 |
| `export.aseprite` | 输出 Aseprite，默认 true；PNG 图集和 manifest 始终保留，作为交付契约 |
| `export.png_frames` | 同时输出透明 PNG 单帧 |
| `export.previews` | 输出动画预览 |
| `export.preview_sizes` | 预览用尺寸，可与正式输出不同 |
| `export.preview_scale` | 预览整数最近邻放大倍数 |
| `export.preview_frames` | 额外循环预览帧数，默认 48；不改变实际交付帧数 |
| `export.zip` | 输出完整交付 ZIP，不包含工作缓存 |

`layout.group` 不存在：分组填在各动画的 `group`。省略 group 时，同一个配置中的全部动画共用一组；不同角色请分组或分配置，避免错误地一起缩放。

### 输入格式

```json
{"name":"walk_right","source":"../input/walk_right.aseprite"}
```

```json
{"name":"walk_right","source":{"path":"../input/sheet.png","frame_size":[512,512],"fps":16}}
```

```json
{"name":"walk_right","source":{"path":"../input/frames","type":"sequence","glob":"*.png","durations_ms":[62,63,62,63]}}
```

- 图集按行优先读取；有 `metadata` 时以 JSON 中的 frame/rect 为准，也支持 Aseprite 导出的 trimmed/sourceSize 信息。
- `durations_ms` 可为单个整数或逐帧列表；未覆盖时使用源 Aseprite/JSON 的时长。仅 PNG 无时长信息时必须提供 fps 或 duration，不猜。
- fps 按累计时间取整生成毫秒时长，16 fps 对应 62/63ms，不强行统一成 62ms。
- 逐帧文件使用自然排序：`2.png` 在 `10.png` 前。请用零填充命名以便其他工具兼容。
- PNG 一张图片可用 `type:image`，仍需给定该帧时长。
- `init` 优先发现所选目录的 Aseprite；没有时发现 PNG+同名 JSON。对于复杂 atlas 或多层子目录，检查配置清单，避免同时选到不同版本或分辨率副本。

### 镜像、倒放、ping-pong

```json
{"name":"walk_left","mirror_of":"walk_right","axis":"horizontal"}
```

方向名称只是标签，不限制为八个罗盘方向。不自动补哪几个方向，也不隐式覆盖已有方向。镜像可引用后面的条目，可以链式引用，但不能循环引用。

`reverse:true` 倒放；`pingpong` 有三种值：

- `none`：不改循环方式。
- `repeat_ends`：`0,1,2,3,4,5,6,7,7,6,5,4,3,2,1,0`，8 → 16；首尾端点重复是明确的配置行为。
- `no_repeat_ends`：`0,1,2,3,4,5,6,7,6,5,4,3,2,1`，8 → 14。

### 已剪辑小图对应高分辨率原帧

```json
{
  "name":"idle_front",
  "source":"../input/original_512.aseprite",
  "edited":"../input/user_edited_64.aseprite",
  "matching":{"allow_mirror":false,"max_error":0.12,"min_margin":0.002,"compare_size":64}
}
```

匹配失败后查看输出中的 `matching/idle_front.json`；以人工确认的 `frame_map:[12,13,14,15,0,1]` 覆盖匹配。索引均从 0 开始。若指定 edited，frame_map 长度必须等于 edited 帧数；继续保留 edited 时长。

匹配是可拒绝的相似度识别，不是“保证找回原帧”。姿态几乎相同、严重去边、重绘、遮挡、比例变化时应手工提供映射。完全相同的候选帧记录等价候选；输出像素不受任选其中一帧影响。

### 逐渐变大的修正

```json
{"name":"walk_front","source":"../input/front.aseprite","zoom":{"start_scale":1.0,"end_scale":0.94,"easing":"smoothstep"}}
```

该项在高分辨率工作画布生效，末帧缩到首帧比例的 0.94；也支持 `linear`。没有此项就不会自动修正。`report.json` 包含每帧应用系数、边界、面积和首尾面积比，供决定是否需要调整。该曲线不能自动保证原来的首尾循环仍然无缝。如果变换将裁掉可见内容，工具会停止，不会默默切掉角色。

### 白边处理的细调

strict 预设沿用之前的轮廓候选检测、邻近有效颜色替换和白色小连通岛处理。可覆盖：

```json
{
  "profile":"strict",
  "edge_width":2,
  "reference_radius":4,
  "alpha_cutoff":8,
  "dust_area":4,
  "opaque_luminance":178,
  "partial_luminance":150,
  "opaque_saturation":0.38,
  "partial_saturation":0.48,
  "opaque_gap":16,
  "partial_gap":12,
  "passes":12
}
```

宽度、半径、连通岛面积按**当前处理阶段的像素**计。建议先看 conservative 与 strict 的差别。角色内部白色不会被全局阈值删除，但贴在轮廓上的合法白色仍可能被当作污染；这是算法边界，不做“零误删”的承诺。`detector_residual:0` 仅表示本检测器无候选，不代表人工视觉已验收。关闭清理仍会把 alpha=0 像素的隐藏 RGB 清零，防止后续污染。

## 输出契约

```text
result/
  config.resolved.json       解析后的完整配置及绝对源路径
  report.json                缩放/帧源/去白/警告记录；complete 或 failed
  verification.json          文件验证结果
  512px/, 64px/, 32px/        名称按实际目标尺寸生成
    aseprite/*.aseprite       全画布 RGBA 单层交付
    sheets/*.png             不 trim、不旋转、不重排的水平图集
    sheets/*.json            rect、索引、毫秒时长、来源、pivot 等
    frames/<name>/*.png      可选单帧
  previews/<size>/            原始长度/指定长度 GIF + APNG + 合集
  matching/*.json             有匹配任务时生成
  work/                      Aseprite 源导出缓存，不放入 ZIP
  <name>_delivery.zip
```

- 导出的 Aseprite **合成为一个 RGBA 图层**，保留交付帧像素、顺序、时长，不承诺保留源文件所有图层、slice、palette、标签或用户元数据；原 Aseprite 始终不改。
- 预览最近邻放大。APNG 保存毫秒时长；GIF 仅支持 10ms 粒度，因此会近似时长。合集根据实际时间取样显示，不作为重新采样后的游戏动画。
- 例如原动画 16 帧、额外预览 48 帧时，后者只是重复播放三遍，不伪装成新生成 48 帧。
- 结果目录已有文件时直接拒绝，不静默续跑、覆盖或删除旧结果。失败会保留报告和中间产物；修复配置后使用新的输出目录。
- 不把白边检测通过、文件可打开、静态导入通过说成游戏播放验收。

## Unity 是可选适配，不绑定项目

```powershell
python spritepost.py unity-check "E:/MyGame/Assets/Sprites/Creature" --config "E:/Jobs/creature.json"
```

此命令**只读** `.png.meta/.aseprite.meta`：检查完整帧矩形、Full Rect、Point、mipmap、压缩、pivot、ID 与纹理尺寸限制。读取 Aseprite 当前启用模式的 metadata，避免把未启用的 tight 数据误认为实际导入。对于无法识别的序列化版本会警告，不伪装成已验证。

`unity.pixels_per_unit`、`unity.pivot` 可自定义；`require_full_rect`、`require_point`、`require_no_mipmaps`、`require_uncompressed` 可关闭。这些只用于可选检查/manifest，不会强行改成某个项目的约束。

显式替换一个已有 PNG：

```powershell
python spritepost.py deploy --sheet "E:/Delivery/creature/64px/sheets/walk_right.png" --manifest "E:/Delivery/creature/64px/sheets/walk_right.json" --destination "E:/MyGame/Assets/Sprites/Creature/walk_right.png" --backup-dir "E:/Backups/Creature"
```

- 目标存在时，必须已经有 `.meta`，且尺寸、帧数、完整矩形及顺序与 manifest 一致；否则拒绝，防止跳帧与引用错位。
- 先备份原 PNG 和 `.meta`，然后原子替换 PNG；**不改 `.meta`、GUID、SpriteID 或 `.anim`**。备份不能放入 Assets 或目标目录内部。
- 新路径只复制 PNG，不伪造 `.meta`；需通过目标引擎建立首次导入。
- 这不是自动重建 Animator/AnimationClip 的工具；不同引擎可以读取 manifest 的累计时长和固定 rect 接入自己的导入器。
- 不自动把生成文件写进工程，不批量调用任何项目的旧迁移脚本。静态检查不能代替目标 Unity 版本的重新导入、引用和游戏播放检查。

## 常见问题

### 提示结果目录已经存在

请选择新的空路径，例如 `creature_delivery_v02`。这是为了避免覆盖已经验收的交付。配置文件也不能放在自己的结果目录里面；例如配置放在 `E:/Jobs/creature.json`，结果放在 `E:/Delivery/creature`。

### 找不到 Python 或缺少依赖

运行“环境检查”或 `Start.cmd doctor`。创建 `.venv`、安装 `requirements.txt`，再通过 `Start.ps1 -Python`、`SPRITEPOST_PYTHON` 或 `runtime.local.json` 指向该解释器。不要直接复制另一台电脑的绝对路径配置。

### 找不到 Aseprite

如果只处理 PNG，可将 `export.aseprite` 设为 false。否则请在界面中选择 Aseprite，或设置 `SPRITEPOST_ASEPRITE`、PATH、配置字段 `aseprite`。

### 原帧匹配存在歧义

打开结果中 `matching/` 下的报告，人工比较候选项，然后填写从 0 开始的明确 `frame_map`。不要只为了消除报错而不断放宽阈值，否则可能接受错误帧。

### 合法白色细节被删，或白色污染仍存在

轮廓存在白毛、白光、雪或羽毛时使用 `conservative` 或 `off`；只有确定边缘受污染时才使用 `strict`。可继续调整边缘宽度、亮度、饱和度、色差、小岛面积和处理轮数。该功能不能替代正确的背景分割和人工视觉检查。

## 回归测试与打包

```powershell
python -m unittest discover -s tests -v
python -m compileall -q spritepost tests gui.py spritepost.py
python build_release.py
```

真实 Aseprite 测试在发现 Aseprite 时执行，找不到时明确 skip。发布包仅包含工具、示例与测试，不含本机路径配置、个人素材、运行缓存或游戏项目内容。
