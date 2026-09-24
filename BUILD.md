# 构建与安装

## 前置条件

- **DevEco Studio**（自带 hvigor 与 HarmonyOS SDK）
- 一台鸿蒙设备或模拟器

> **hap 只能由 DevEco Studio / hvigor 产出。** ArkTS 需要被编译成 `.abc` 字节码，
> 这依赖 SDK 里的 `ets-loader`、`restool` 等组件，而 SDK 只随 DevEco Studio 分发
> （官方 command-line-tools 需要华为开发者账号下载；`@ohos/hvigor` 也不在公开 npm 源上）。
>
> 本仓库的 `tools/` 只负责**生成站点资源并同步进 `app/.../rawfile/`**，不产出 hap。
> 也就是说：改站点内容 → 跑 `tools/sync_to_app.sh` → 回 DevEco 点一次 Run。

## 1. 打开工程

`File → Open`，选择本仓库的 **`app/`** 目录（不是仓库根，也不是 `app/entry`）。

工程没有任何第三方依赖（`dependencies` / `devDependencies` 均为空），
`ohpm install` 不需要下载东西，Sync 应该很快。

## 2. 确认 SDK 版本

`app/build-profile.json5` 里写的是：

```json5
"targetSdkVersion": "5.0.0(12)",
"compatibleSdkVersion": "5.0.0(12)",
```

这是有意选的**保守值**，兼容面最广。本工程用到的 ArkWeb 能力
（`Web` 组件、`WebviewController`、`setWindowLayoutFullScreen`）在 API 9 就已具备，
不需要更高版本。

若 Sync 报 `Invalid value of compileSdkVersion, compatibleSdkVersion, or targetSdkVersion`：
**几乎都是格式问题** —— HarmonyOS 工程必须写成 `M.S.F(API)` 形式（如 `5.0.0(12)`），
裸数字 `12` 或 `26.0.0` 都是错的。最省事的修法是走
`File → Project Structure → Project`，用下拉框选，GUI 写进去的一定对。
约束是 `compatibleSdkVersion ≤ targetSdkVersion ≤ compileSdkVersion`。

若报 `modelVersion is not supported` 并要求升级：同意自动升级即可
（工程当前是 `5.0.0`，位于 `app/oh-package.json5` 与 `app/hvigor/hvigor-config.json5`，两处需一致）。

## 3. 配置签名

`File → Project Structure → Signing Configs`，勾选 **Automatically generate signature**，
按提示登录华为开发者账号，它会生成调试证书并写回 `build-profile.json5`。

工程的 `signingConfigs` 是**故意留空**的，就是为了让这一步自动完成。

> 签名用的 `.p12` 密码由 DevEco 随机生成并加密保存在工程配置里，
> 外部工具（`hapsigntool` / `keytool`）打不开，所以**无法在 DevEco 之外重新签名**。

## 4. 运行到设备

连上设备（USB 或无线调试），顶部设备下拉框里选中它，点绿色 **Run**。

无线调试连接（设备上开启「无线调试」后，用显示出来的 IP:端口）：

```bash
hdc tconn <ip>:<port>
hdc list targets
```

装好后启动后是全屏的深色三维场景。

## 出错排查

| 现象 | 原因 | 处理 |
| --- | --- | --- |
| `modelVersion is not supported` | DevEco 版本与工程模型版本不匹配 | 同意自动升级，或按提示改 `oh-package.json5` 与 `hvigor/hvigor-config.json5`（两处要一致） |
| `Invalid value of compileSdkVersion…` + Sync cancelled | 版本号格式写错 | 必须 `M.S.F(API)`，见第 2 步 |
| Sync 反复失败 | `hvigor/hvigor-config.json5` 缺失或结构损坏 | 本工程已带该文件；可查看 `app/.bitfun/.deveco/project.cache.json` 的 `lastOhpmInstallResult` |
| `00303038 Configuration Error / Schema validate failed` | `module.json5` 里写了 schema 不认的字段 | 报错会同时打印允许字段全清单，照着比对 |
| `Argument of type '(event: X) => void' is not assignable to parameter of type 'Callback<X, boolean>'` | ArkWeb 的 `onConsole` / `onErrorReceive` 回调**要求返回值** | 回调里写 `return false`（不消费事件，交回系统默认处理）。本工程已修 |
| 编译通过但安装报设备类型不支持 | `module.json5` 的 `deviceTypes` 没包含目标形态 | 本工程已列 `["phone", "tablet", "2in1"]` |
| `$media:xxx` / `$string:xxx` / `$profile:xxx` 找不到 | 资源缺失或名字拼错 | 跑 `python3 tools/validate_project.py`，会精确指出是哪个引用 |
| **应用打开是黑屏/白屏（只有界面外壳）** | 站点被当成 ES 模块加载了 | `resource://` 下 module 脚本会被 CORS 拒绝，见 README「实现上值得说明的三点」。确认 `rawfile/index.html` 里**不含** `type="module"` |
| 界面正常但统计行/图例是空的 | 站点 JS 没执行 | 同上 |

工程静态自检（不需要编译器，改完随时跑）：

```bash
python3 tools/validate_project.py
```

会校验：配置可解析、所有 `$media/$string/$color/$profile` 引用有实体、
`main_pages.json` 与 `EntryAbility.loadContent` 一致、ArkTS 无禁用语法、
`rawfile/index.html` 是自包含单文件（出现 module 脚本或本地外部引用即判为错误）。

## 更新站点内容

```bash
sh tools/sync_to_app.sh
```

依次做：`tsc` 编译 → 打包自包含单文件 → 同步进 `app/.../rawfile/` → 工程自检。
完了在 DevEco 里点一次 Run。

> **不要**手工把 `site/` 的多文件版本拷进 rawfile —— 那是 ESM，
> `resource://` 下必然白屏。进 rawfile 的只能是打包脚本产出的那个单文件。

`rawfile` 里的内容随包发出，**运行时不发起任何网络请求**。

## 重新生成应用图标

```bash
cd tools/appicon
python3 make_icon.py          # 需要 PIL
```

生成 `icon_background.png`（星空）/ `icon_foreground.png`（地球）/ `icon_start.png`（启动图标），
把它们覆盖到 `app/AppScope/resources/base/media/` 与 `app/entry/src/main/resources/base/media/`。

前景层里地球占前景图宽度的比例由脚本里的 `ZOOM` 常量控制 ——
系统会把前景缩放后叠加到背景上，实际观感以桌面为准，偏大偏小改这个常量重渲即可。
