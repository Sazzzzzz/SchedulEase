# SchedulEase

**NKU 选课，从未如此优雅（ *~~bushi~~* ）**

`SchedulEase` 是一款专为南开大学学子打造的 TUI (文本用户界面) 选课助手。它致力于将你从每年两次的选课焦虑和浏览器F5中解放出来。

**核心功能:**

+ **一站式选课:** 无论是公选课、专选课还是体育课，都在一个界面搞定。
+ **智能防冲突:** 内置课程表，实时预览，规避时间冲突。
+ **定时选课:** 设置好目标课程，倒计时一到，程序将自动发送选课请求。

> **免责声明:** 本应用的 *~~优雅~~* 很大程度上取决于您终端的美化配置和个人审美。作者对因终端主题过丑导致的任何问题概不负责 : P

## 免责声明

> [!WARNING]
> 南开大学教务处明令禁止使用第三方软件进行选课。
>
> 本项目仅供学习交流，旨在探索 TUI 应用开发与后端 API 交互。对于任何使用本软件造成的后果——包括但不限于选课失败、账号异常等——开发者概不负责。
>
> 该项目以 [Unlicensed](./LICENSE) 许可证开源，你可以自由学习、修改和使用，但开发者不提供任何形式的担保，也不承担任何责任。

## 食用指南

### 方式一：Binary Release

适合只想快速搞定选课的同学：

1. 前往右侧的 **[Releases](https://github.com/Sazzzzzz/SchedulEase/releases)** 页面，下载对应你操作系统的最新版本。
2. 双击运行即可！
    + macOS 用户可能需要**右键点击 -> 打开**以运行`SchedulEase` 。

> [!TIP] **测试模式**
>
> 在非选课时段，本程序绝大部分功能将不可用。如需体验或测试，请务必在**测试模式**下运行。
>
> 打开你的终端 (Terminal / PowerShell)，进入程序所在目录，然后运行：
>
> ```bash
> # Windows
> ./schedulease.exe --test
>
> # macOS / Linux
> ./schedulease --test
> ```

> 数据采集自2025年NKU暑假小学期课程表。


### 方式二：Dev Mode

适合对Python有一定经验的同学：

1. **克隆代码到本地:**

    ```bash
    git clone https://github.com/Sazzzzzz/SchedulEase.git
    cd SchedulEase
    ```

2. **创建虚拟环境并安装依赖 (推荐使用 `uv`):**

    + **使用 `uv`**

        ```bash
        # 创建虚拟环境
        uv venv
        
        # 激活环境
        # Windows (PowerShell)
        .venv\Scripts\Activate.ps1 
        # macOS / Linux
        source .venv/bin/activate
        
        # 安装依赖
        uv pip install -e .
        ```

    + **使用传统 `pip`:**

        ```bash
        # (确保你已安装 Python) 创建并激活虚拟环境
        python -m venv .venv
        # ...参考上面的命令激活环境...

        # 安装依赖
        pip install -e .
        ```

3. **启动！**
    安装完成后，直接在终端中输入命令即可启动：

    ```bash
    schedulease
    ```

## 项目架构

*To be added...*

## 开发者笔记

欢迎任何形式的贡献！

首先，安装开发模式所需的依赖：

```bash
# 使用 uv
uv pip install -e ".[dev]"

# 使用 pip
pip install -e ".[dev]"
```

以下是部分教务系统的 API 开发资料：

+ [API 研究笔记 (Jupyter Notebook)](https://github.com/Sazzzzzz/SchedulEase/blob/main/reference/eamis_api.ipynb)
+ [相关参考资料目录](https://github.com/Sazzzzzz/SchedulEase/tree/main/reference)
